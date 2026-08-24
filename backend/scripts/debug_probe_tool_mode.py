"""
LLM 工具协议能力探测脚本（内网网关 function call 确认用）

用途：
    确认目标 LLM 网关是否支持原生 function call（tools 参数透传）。
    分两层验证：
    - L1 非流式：发送带 tools 的请求，检测 finish_reason == "tool_calls" 且 tool_calls 结构完整
    - L2 流式：按 index 累积 arguments 分片，校验最终 JSON 合法性

用法（在 portfilio-end 目录下）：
    python scripts/debug_probe_tool_mode.py
    python scripts/debug_probe_tool_mode.py --base-url http://203.5.221.155:8000/v1 --model Qwen3-235B-A22B-PPU

结论判定：
    - L1 + L2 均通过 → 可在 .env 设置 LLM_TOOL_MODE=native
    - 任一失败       → 维持默认 LLM_TOOL_MODE=soft（软工具模式）

注意：本脚本为一次性诊断工具，不进主链路，不依赖 app.agent 之外的任何业务模块。
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# 允许从 scripts/ 目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI  # noqa: E402

# 探测用的最小工具定义（模拟系统真实工具形态）
_PROBE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "获取当前系统日期，用于时间相关查询",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "时区名称，如 Asia/Shanghai",
                    }
                },
                "required": [],
            },
        },
    }
]

_PROBE_MESSAGES = [
    {"role": "system", "content": "你是一个测试助手，需要时请调用工具。"},
    {"role": "user", "content": "请调用工具查询当前日期。"},
]


def _load_env_defaults() -> tuple[str, str, str]:
    """从 app.agent.core.config 读取默认网关配置"""
    try:
        from app.agent.core.config import get_agent_settings
        s = get_agent_settings()
        return s.LLM_BASE_URL, s.LLM_API_KEY, s.LLM_MODEL
    except Exception as e:
        print(f"[warn] 读取 AgentSettings 失败（{e}），请通过命令行参数指定网关配置")
        return "", "", ""


async def probe_l1(client: AsyncOpenAI, model: str) -> tuple[bool, str]:
    """L1：非流式带 tools 请求，检测原生 tool_calls 输出"""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=_PROBE_MESSAGES,
            tools=_PROBE_TOOLS,
            tool_choice="auto",
        )
    except Exception as e:
        return False, f"请求异常（网关可能拒绝 tools 参数）: {e}"

    choice = resp.choices[0]
    finish_reason = choice.finish_reason
    tool_calls = choice.message.tool_calls

    if finish_reason == "tool_calls" and tool_calls:
        tc = tool_calls[0]
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            return False, f"tool_calls 已返回但 arguments 非合法 JSON: {tc.function.arguments[:100]}"
        return True, (
            f"finish_reason=tool_calls, name={tc.function.name}, "
            f"id={tc.id}, arguments={json.dumps(args, ensure_ascii=False)}"
        )

    content_preview = (choice.message.content or "")[:120].replace("\n", " ")
    return False, (
        f"finish_reason={finish_reason}, tool_calls 为空"
        f"（模型以纯文本回复: {content_preview!r}）→ 网关可能拦截了 tools 参数"
    )


async def probe_l2(client: AsyncOpenAI, model: str) -> tuple[bool, str]:
    """L2：流式请求按 index 累积 arguments 分片，校验 JSON 合法性"""
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=_PROBE_MESSAGES,
            tools=_PROBE_TOOLS,
            tool_choice="auto",
            stream=True,
        )
    except Exception as e:
        return False, f"流式请求异常: {e}"

    acc: dict[int, dict] = {}
    finish_reason = None
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason or finish_reason
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                entry = acc.setdefault(tc_delta.index, {"id": "", "name": "", "arguments": ""})
                if tc_delta.id:
                    entry["id"] = tc_delta.id
                if tc_delta.function and tc_delta.function.name:
                    entry["name"] += tc_delta.function.name
                if tc_delta.function and tc_delta.function.arguments:
                    entry["arguments"] += tc_delta.function.arguments
        if finish_reason == "tool_calls":
            break

    if not acc:
        return False, f"流式未收到任何 tool_call 分片（finish_reason={finish_reason}）"

    for idx, entry in sorted(acc.items()):
        try:
            json.loads(entry["arguments"] or "{}")
        except json.JSONDecodeError as e:
            return False, f"index={idx} 累积的 arguments 非合法 JSON: {e}，内容: {entry['arguments'][:100]}"

    entry = acc[min(acc)]
    return True, (
        f"共 {len(acc)} 个工具调用，分片累积完整；"
        f"name={entry['name']}, id={entry['id']}, arguments={entry['arguments']}"
    )


async def main():
    parser = argparse.ArgumentParser(description="LLM 原生 function call 能力探测")
    parser.add_argument("--base-url", default=None, help="LLM 网关地址（默认读 .env 的 LLM_BASE_URL）")
    parser.add_argument("--api-key", default=None, help="API Key（默认读 .env 的 LLM_API_KEY）")
    parser.add_argument("--model", default=None, help="模型名（默认读 .env 的 LLM_MODEL）")
    args = parser.parse_args()

    env_base_url, env_key, env_model = _load_env_defaults()
    base_url = args.base_url or env_base_url
    api_key = args.api_key or env_key
    model = args.model or env_model

    if not base_url or not model:
        print("[error] 缺少 base_url 或 model，请通过参数或 .env 配置")
        sys.exit(2)

    print("=" * 64)
    print(f"探测目标: base_url={base_url}")
    print(f"          model={model}")
    print("=" * 64)

    client = AsyncOpenAI(api_key=api_key or "EMPTY", base_url=base_url)

    ok1, detail1 = await probe_l1(client, model)
    print(f"\n[L1 非流式] {'通过' if ok1 else '未通过'}")
    print(f"    {detail1}")

    ok2, detail2 = await probe_l2(client, model)
    print(f"\n[L2 流式累积] {'通过' if ok2 else '未通过'}")
    print(f"    {detail2}")

    print("\n" + "=" * 64)
    if ok1 and ok2:
        print("结论：网关支持原生 function call。")
        print("操作：在 portfilio-end/.env 中设置 LLM_TOOL_MODE=native 并重启后端，")
        print("      回归验证对话链路后可按计划删除 SoftToolProtocol。")
    else:
        print("结论：网关不支持（或不稳定支持）原生 function call。")
        print("操作：维持默认 LLM_TOOL_MODE=soft，可按计划删除 NativeToolProtocol。")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())

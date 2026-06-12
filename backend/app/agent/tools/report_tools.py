"""
报告类工具 — 策略研究报告自动生成

提供 1 个报告相关 BaseTool：
- generate_strategy_report  基于对话历史自动生成单一策略研究报告

设计规范：
- 所有数值从工具返回值原样提取，不做推测或自行计算
- 对比表格直接引用，不改写
- 缺失步骤标注 "[本次研究未执行此步骤]"
- 收益率/波动率保留2位小数，夏普比2-3位，权重2位
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.services.conversation_store import ConversationStore
from app.services.report_service import ReportService

_NOT_EXECUTED = "[本次研究未执行此步骤]"

# 需要提取的工具名称集合
_TRACKED_TOOLS: set[str] = {
    "query_assets",
    "recommend_strategy",
    "compare_strategies",
    "execute_backtest",
    "compute_weights",
    "create_strategy_model",
}


class GenerateStrategyReportTool(BaseTool):
    """基于对话历史自动生成策略研究报告"""

    name = "generate_strategy_report"
    description = (
        "基于当前对话的策略研究历史，自动生成单一策略研究报告。"
        "从对话中提取资产查询、策略推荐、回测对比、权重计算等工具调用结果，"
        "生成结构化研究报告并保存到报告中心。"
    )
    category = "report"
    tags = ["报告", "策略研究", "总结"]
    parameters = {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": "当前对话ID，用于读取对话历史",
            },
            "title": {
                "type": "string",
                "description": "报告标题，不传时自动生成",
            },
            "research_goal": {
                "type": "string",
                "description": "研究目标简述，不传时从对话中推断",
            },
        },
        "required": ["conversation_id"],
    }

    # ── execute ────────────────────────────────────────────

    def set_tracker(self, tracker):
        """注入工具结果跟踪器"""
        self._tool_result_tracker = tracker

    async def execute(self, **kwargs: Any) -> dict:
        """执行报告生成流程"""
        conversation_id: str = kwargs["conversation_id"]
        title: str | None = kwargs.get("title")
        research_goal: str | None = kwargs.get("research_goal")

        # 从 tool_context 中获取 tracker（若有）
        tracker = kwargs.get("_tool_result_tracker")
        if tracker is not None:
            self._tool_result_tracker = tracker

        # ── 步骤1: 获取工具调用结果（优先使用 tracker 增量数据） ──
        if hasattr(self, '_tool_result_tracker') and self._tool_result_tracker.has_data():
            # 使用增量收集的数据，无需全量扫描
            tool_results = self._tool_result_tracker.get_tool_results_for_report()
            # 仍需少量历史来提取用户消息
            store = ConversationStore()
            messages = await store.get_messages(conversation_id, limit=30)
            logger.info(
                "report_using_tracker_data",
                extra={"conversation_id": conversation_id, "tracked_tools": list(tool_results.keys())},
            )
        else:
            # 降级方案：从历史加载但限制为50条
            store = ConversationStore()
            messages = await store.get_messages(conversation_id, limit=50)
            if not messages:
                return ToolResult.error("对话历史为空，无法生成报告")
            logger.info(
                "report_messages_loaded_fallback",
                extra={"conversation_id": conversation_id, "count": len(messages)},
            )
            tool_results = self._extract_tool_results(messages)

        user_messages = [
            m.get("content", "") for m in (messages or []) if m.get("role") == "user"
        ]

        # ── 步骤3: 组装 data_context ──
        data_context = {
            "template_type": "strategy_research",
            "report_title": title or self._generate_title(tool_results),
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "asset_names": self._extract_asset_names(tool_results),
            "recommended_strategy": self._extract_recommended_strategy(tool_results),
            "research_background": (
                research_goal
                or self._extract_research_background(tool_results, user_messages)
            ),
            "asset_list_table": self._build_asset_table(tool_results),
            "initial_config": self._extract_initial_config(tool_results),
            "candidate_strategies": self._extract_candidate_strategies(tool_results),
            "comparison_table": self._extract_comparison_table(tool_results),
            "comparison_conclusion": self._extract_comparison_conclusion(tool_results),
            "asset_adjustment": self._extract_asset_adjustment(tool_results),
            "adjusted_comparison": self._extract_adjusted_comparison(tool_results),
            "final_recommendation": self._extract_final_recommendation(tool_results),
            "weight_allocation": self._extract_weight_allocation(tool_results),
            "metrics_summary_table": self._build_metrics_summary(tool_results),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        # ── 步骤4: 控制 data_context 总大小不超过 8000 字符 ──
        context_str = json.dumps(data_context, ensure_ascii=False, default=str)
        if len(context_str) > 8000:
            # 逐步削减：先截断大表格字段
            for key in ["asset_list_table", "comparison_table", "adjusted_comparison", "metrics_summary_table"]:
                if data_context.get(key) and len(str(data_context[key])) > 1000:
                    data_context[key] = str(data_context[key])[:1000] + "\n... (已截断)"
            context_str = json.dumps(data_context, ensure_ascii=False, default=str)
            if len(context_str) > 8000:
                # 最终兆底：移除非关键字段
                for key in ["asset_adjustment", "adjusted_comparison", "initial_config"]:
                    data_context.pop(key, None)
            logger.info("report_data_context_trimmed", extra={"final_size": len(json.dumps(data_context, ensure_ascii=False, default=str))})

        # ── 步骤5: 调用 ReportService 生成报告 ──
        report_service = ReportService()
        try:
            result = await report_service.generate_draft(
                "strategy_research_report", data_context
            )
        except Exception as e:
            logger.error(
                "report_generate_draft_failed",
                extra={"conversation_id": conversation_id, "error": str(e)},
            )
            return ToolResult.error(f"报告生成失败: {e}")

        if not result.get("success"):
            return ToolResult.error(result.get("error", "报告模板渲染失败"))

        # ── 步骤6: 统计章节数并返回 ──
        rendered = result.get("rendered_content", "")
        section_count = rendered.count("\n## ")

        logger.info(
            "report_generated",
            extra={
                "conversation_id": conversation_id,
                "report_id": result["report_id"],
                "section_count": section_count,
            },
        )

        return {
            "success": True,
            "data": {
                "report_id": result["report_id"],
                "title": data_context["report_title"],
                "template_type": "strategy_research",
                "content_length": len(rendered),
                "rendered_content": rendered,
            },
            "summary": (
                f"已生成策略研究报告「{data_context['report_title']}」，"
                f"包含 {section_count} 个章节"
            ),
        }

    # ── 工具结果提取 ─────────────────────────────────────────

    def _extract_tool_results(self, messages: list[dict]) -> dict[str, list[dict]]:
        """从对话消息中提取各工具的调用结果"""
        tool_results: dict[str, list[dict]] = {name: [] for name in _TRACKED_TOOLS}

        # 先建立 tool_call_id -> tool_name 映射
        call_id_map: dict[str, str] = {}
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id", "")
                fn_name = ""
                func_obj = tc.get("function")
                if isinstance(func_obj, dict):
                    fn_name = func_obj.get("name", "")
                if tc_id and fn_name:
                    call_id_map[tc_id] = fn_name
            # 兼容 tool_calls_raw 字段
            for tc in msg.get("tool_calls_raw", []):
                tc_id = tc.get("id", "")
                fn_name = ""
                func_obj = tc.get("function")
                if isinstance(func_obj, dict):
                    fn_name = func_obj.get("name", "")
                if tc_id and fn_name:
                    call_id_map[tc_id] = fn_name

        # 遍历 tool 角色消息，解析内容
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            tool_call_id = msg.get("tool_call_id", "")
            tool_name = call_id_map.get(tool_call_id, "")
            if tool_name not in _TRACKED_TOOLS:
                continue

            content = msg.get("content", "")
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                logger.debug(
                    "report_tool_content_parse_skip",
                    extra={"tool_name": tool_name, "tool_call_id": tool_call_id},
                )
                continue

            if isinstance(parsed, dict):
                tool_results[tool_name].append(parsed)

        logger.info(
            "report_tool_results_extracted",
            extra={k: len(v) for k, v in tool_results.items()},
        )
        return tool_results

    # ── 辅助提取方法 ─────────────────────────────────────────

    def _generate_title(self, tool_results: dict[str, list[dict]]) -> str:
        """从工具结果自动生成报告标题"""
        asset_names = self._extract_asset_names(tool_results)
        strategy = self._extract_recommended_strategy(tool_results)
        if asset_names != "—" and strategy != "—":
            return f"{asset_names} - {strategy}策略研究报告"
        if asset_names != "—":
            return f"{asset_names}策略研究报告"
        return f"策略研究报告_{datetime.now().strftime('%Y%m%d')}"

    def _extract_asset_names(self, tool_results: dict[str, list[dict]]) -> str:
        """从 query_assets 结果中提取资产名称"""
        results = tool_results.get("query_assets", [])
        if not results:
            return "—"
        latest = results[-1]
        data = latest.get("data", latest)
        # 尝试从 assets 列表中提取名称
        assets = data.get("assets", [])
        if assets:
            names = [a.get("name", a.get("code", "")) for a in assets]
            return ", ".join(n for n in names if n)
        # 兼容: 直接取 asset_names 字段
        if isinstance(data.get("asset_names"), list):
            return ", ".join(data["asset_names"])
        return "—"

    def _extract_recommended_strategy(
        self, tool_results: dict[str, list[dict]]
    ) -> str:
        """提取推荐策略名称"""
        results = tool_results.get("recommend_strategy", [])
        if not results:
            return "—"
        latest = results[-1]
        data = latest.get("data", latest)
        return data.get("recommended", data.get("strategy_name", "—"))

    def _extract_research_background(
        self, tool_results: dict[str, list[dict]], user_messages: list[str]
    ) -> str:
        """从用户消息推断研究背景"""
        if user_messages:
            # 取前几条用户消息拼接，截断到合理长度
            combined = " ".join(user_messages[:3])
            if combined.strip():
                return combined[:500]
        return _NOT_EXECUTED

    def _build_asset_table(self, tool_results: dict[str, list[dict]]) -> str:
        """构建资产列表 GFM 表格"""
        results = tool_results.get("query_assets", [])
        if not results:
            return _NOT_EXECUTED
        latest = results[-1]
        data = latest.get("data", latest)
        assets = data.get("assets", [])
        if not assets:
            return _NOT_EXECUTED

        lines = ["| 资产代码 | 资产名称 | 资产类型 |", "| --- | --- | --- |"]
        for a in assets:
            code = a.get("code", "—")
            name = a.get("name", "—")
            asset_type = a.get("type", a.get("asset_type", "—"))
            lines.append(f"| {code} | {name} | {asset_type} |")
        return "\n".join(lines)

    def _extract_initial_config(self, tool_results: dict[str, list[dict]]) -> str:
        """提取初始策略配置"""
        results = tool_results.get("create_strategy_model", [])
        if not results:
            return _NOT_EXECUTED
        latest = results[-1]
        data = latest.get("data", latest)
        config_parts: list[str] = []
        if data.get("strategy_type"):
            config_parts.append(f"- **策略类型**: {data['strategy_type']}")
        if data.get("rebalance_frequency"):
            config_parts.append(f"- **调仓频率**: {data['rebalance_frequency']}")
        if data.get("lookback_days"):
            config_parts.append(f"- **回看天数**: {data['lookback_days']}")
        if data.get("params"):
            config_parts.append(f"- **参数配置**: {json.dumps(data['params'], ensure_ascii=False)}")
        return "\n".join(config_parts) if config_parts else _NOT_EXECUTED

    def _extract_candidate_strategies(
        self, tool_results: dict[str, list[dict]]
    ) -> str:
        """提取候选策略列表"""
        results = tool_results.get("recommend_strategy", [])
        if not results:
            return _NOT_EXECUTED
        latest = results[-1]
        data = latest.get("data", latest)
        candidates = data.get("candidates", data.get("strategies", []))
        if not candidates:
            # 兼容单条推荐
            name = data.get("recommended", data.get("strategy_name"))
            if name:
                return f"- {name}"
            return _NOT_EXECUTED

        lines: list[str] = []
        for c in candidates:
            if isinstance(c, dict):
                name = c.get("name", c.get("strategy_name", ""))
                desc = c.get("description", c.get("reason", ""))
                lines.append(f"- **{name}**: {desc}" if desc else f"- {name}")
            else:
                lines.append(f"- {c}")
        return "\n".join(lines)

    def _extract_comparison_table(self, tool_results: dict[str, list[dict]]) -> str:
        """直接引用 compare_strategies 返回的对比表格"""
        results = tool_results.get("compare_strategies", [])
        if not results:
            return _NOT_EXECUTED
        latest = results[-1]
        data = latest.get("data", latest)
        # 优先取已格式化的 comparison_table
        table = data.get("comparison_table", "")
        if table:
            return table
        # 兼容: 尝试从 results 构建
        compare_results = data.get("results", [])
        if not compare_results:
            return _NOT_EXECUTED
        return self._build_comparison_from_results(compare_results)

    def _build_comparison_from_results(self, compare_results: list[dict]) -> str:
        """从对比结果列表构建 GFM 表格"""
        headers = ["策略", "累计收益", "年化收益", "年化波动率", "夏普比率", "最大回撤"]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for r in compare_results:
            name = r.get("strategy_name", r.get("name", "—"))
            cum_ret = self._fmt_pct(r.get("cumulative_return"))
            ann_ret = self._fmt_pct(r.get("annual_return", r.get("annualized_return")))
            ann_vol = self._fmt_pct(r.get("annual_volatility", r.get("annualized_volatility")))
            sharpe = self._fmt_ratio(r.get("sharpe_ratio"))
            max_dd = self._fmt_pct(r.get("max_drawdown"))
            lines.append(f"| {name} | {cum_ret} | {ann_ret} | {ann_vol} | {sharpe} | {max_dd} |")
        return "\n".join(lines)

    def _extract_comparison_conclusion(
        self, tool_results: dict[str, list[dict]]
    ) -> str:
        """提取对比结论"""
        results = tool_results.get("compare_strategies", [])
        if not results:
            return ""
        latest = results[-1]
        data = latest.get("data", latest)
        return data.get("conclusion", data.get("summary", ""))

    def _extract_asset_adjustment(self, tool_results: dict[str, list[dict]]) -> str:
        """提取资产调整信息（若有多次 query_assets 调用）"""
        results = tool_results.get("query_assets", [])
        if len(results) < 2:
            return _NOT_EXECUTED
        # 对比首末两次资产变化
        first_data = results[0].get("data", results[0])
        last_data = results[-1].get("data", results[-1])
        first_assets = {a.get("code") for a in first_data.get("assets", [])}
        last_assets = {a.get("code") for a in last_data.get("assets", [])}
        added = last_assets - first_assets
        removed = first_assets - last_assets
        parts: list[str] = []
        if added:
            parts.append(f"- **新增资产**: {', '.join(added)}")
        if removed:
            parts.append(f"- **移除资产**: {', '.join(removed)}")
        if not parts:
            parts.append("- 资产组合未发生变化")
        return "\n".join(parts)

    def _extract_adjusted_comparison(
        self, tool_results: dict[str, list[dict]]
    ) -> str:
        """提取调整后的策略对比（取第二次 compare_strategies 结果）"""
        results = tool_results.get("compare_strategies", [])
        if len(results) < 2:
            return _NOT_EXECUTED
        latest = results[-1]
        data = latest.get("data", latest)
        table = data.get("comparison_table", "")
        if table:
            return table
        compare_results = data.get("results", [])
        if compare_results:
            return self._build_comparison_from_results(compare_results)
        return _NOT_EXECUTED

    def _extract_final_recommendation(
        self, tool_results: dict[str, list[dict]]
    ) -> str:
        """提取最终策略推荐"""
        # 优先从 recommend_strategy 最新结果
        results = tool_results.get("recommend_strategy", [])
        if results:
            latest = results[-1]
            data = latest.get("data", latest)
            name = data.get("recommended", data.get("strategy_name", ""))
            reason = data.get("reason", data.get("description", ""))
            if name:
                text = f"**推荐策略**: {name}"
                if reason:
                    text += f"\n\n**推荐理由**: {reason}"
                return text
        return _NOT_EXECUTED

    def _extract_weight_allocation(self, tool_results: dict[str, list[dict]]) -> str:
        """从 compute_weights 结果构建权重分配表格"""
        results = tool_results.get("compute_weights", [])
        if not results:
            return _NOT_EXECUTED
        latest = results[-1]
        data = latest.get("data", latest)
        weights = data.get("weights", {})
        if not weights:
            return _NOT_EXECUTED

        lines = ["| 资产 | 权重 |", "| --- | --- |"]
        if isinstance(weights, dict):
            for asset, w in weights.items():
                lines.append(f"| {asset} | {self._fmt_weight(w)} |")
        elif isinstance(weights, list):
            for item in weights:
                if isinstance(item, dict):
                    asset = item.get("asset", item.get("code", "—"))
                    w = item.get("weight", 0)
                    lines.append(f"| {asset} | {self._fmt_weight(w)} |")
        return "\n".join(lines)

    def _build_metrics_summary(self, tool_results: dict[str, list[dict]]) -> str:
        """汇总核心指标构建 GFM 表格"""
        # 从 compare_strategies 或 execute_backtest 中提取
        rows: list[dict[str, Any]] = []

        # 优先从对比结果
        for cr in tool_results.get("compare_strategies", []):
            data = cr.get("data", cr)
            for r in data.get("results", []):
                rows.append(r)

        # 补充单次回测
        for bt in tool_results.get("execute_backtest", []):
            data = bt.get("data", bt)
            if data.get("strategy_name") or data.get("name"):
                rows.append(data)

        if not rows:
            return _NOT_EXECUTED

        # 去重（按策略名）
        seen: set[str] = set()
        unique_rows: list[dict[str, Any]] = []
        for r in rows:
            name = r.get("strategy_name", r.get("name", "unknown"))
            if name not in seen:
                seen.add(name)
                unique_rows.append(r)

        headers = ["策略", "累计收益", "年化收益", "年化波动率", "夏普比率", "最大回撤"]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for r in unique_rows:
            name = r.get("strategy_name", r.get("name", "—"))
            cum_ret = self._fmt_pct(r.get("cumulative_return"))
            ann_ret = self._fmt_pct(r.get("annual_return", r.get("annualized_return")))
            ann_vol = self._fmt_pct(r.get("annual_volatility", r.get("annualized_volatility")))
            sharpe = self._fmt_ratio(r.get("sharpe_ratio"))
            max_dd = self._fmt_pct(r.get("max_drawdown"))
            lines.append(f"| {name} | {cum_ret} | {ann_ret} | {ann_vol} | {sharpe} | {max_dd} |")
        return "\n".join(lines)

    # ── 数值格式化 ─────────────────────────────────────────

    @staticmethod
    def _fmt_pct(value: Any) -> str:
        """格式化百分比，保留2位小数"""
        if value is None:
            return "—"
        try:
            v = float(value)
            return f"{v:.2%}" if abs(v) < 10 else f"{v:.2f}%"
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _fmt_ratio(value: Any) -> str:
        """格式化比率（夏普等），保留2-3位小数"""
        if value is None:
            return "—"
        try:
            return f"{float(value):.3f}"
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _fmt_weight(value: Any) -> str:
        """格式化权重，保留2位小数百分比"""
        if value is None:
            return "—"
        try:
            v = float(value)
            # 权重可能是 0-1 小数或 0-100 百分比
            if v <= 1.0:
                return f"{v:.2%}"
            return f"{v:.2f}%"
        except (ValueError, TypeError):
            return str(value)

"""
错误分类与智能重试模块

将 LLM/工具错误分为 6 个类别（速率限制、上下文超长、工具失败、认证错误、网络错误、致命错误），
配合指数退避算法实现智能自动恢复。
"""
import asyncio
import re
from enum import Enum
from dataclasses import dataclass

from loguru import logger


# ======================================================================
# 工具执行层面的错误分类与诊断
# 用于对具体工具的 execute() 抛出的异常进行分类，
# 与下方 ErrorCategory（LLM 请求层面）并列使用。
# ======================================================================

class ToolErrorCategory(str, Enum):
    """工具执行错误分类"""
    PARAMETER_ERROR = "parameter_error"        # 参数格式/类型错误
    BUSINESS_LOGIC = "business_logic"          # 业务逻辑错误（如资产不存在）
    DEPENDENCY_MISSING = "dependency_missing"  # 前置工具未调用
    TIMEOUT = "timeout"                        # 工具执行超时
    NOT_FOUND = "not_found"                    # 资源不存在
    SYSTEM_ERROR = "system_error"              # 系统/网络错误


def classify_tool_error(tool_name: str, error: Exception, args: dict | None = None) -> ToolErrorCategory:
    """根据异常信息分类工具执行错误"""
    error_str = str(error).lower()

    if isinstance(error, asyncio.TimeoutError):
        return ToolErrorCategory.TIMEOUT

    # 参数相关关键词
    if any(kw in error_str for kw in [
        "参数", "parameter", "required", "invalid", "missing",
        "type error", "validation", "typeerror", "valueerror",
    ]):
        return ToolErrorCategory.PARAMETER_ERROR

    # 资源不存在
    if any(kw in error_str for kw in [
        "not found", "不存在", "找不到", "no data", "empty",
    ]):
        return ToolErrorCategory.NOT_FOUND

    # 业务逻辑
    if any(kw in error_str for kw in [
        "策略", "权重", "回测", "资产", "strategy", "weight", "backtest",
    ]):
        return ToolErrorCategory.BUSINESS_LOGIC

    # 网络/系统
    if any(kw in error_str for kw in [
        "connection", "network", "timeout", "refused", "dns",
    ]):
        return ToolErrorCategory.SYSTEM_ERROR

    # 默认归类为业务逻辑错误
    return ToolErrorCategory.BUSINESS_LOGIC


def generate_tool_diagnosis(
    tool_name: str,
    error: Exception,
    category: ToolErrorCategory,
    args: dict | None = None,
) -> str:
    """根据错误分类生成结构化诊断信息"""
    error_str = str(error)

    if category == ToolErrorCategory.PARAMETER_ERROR:
        return f"参数格式错误：{error_str}。请核对 {tool_name} 的参数 schema，确认字段名称、类型和必填项。"

    if category == ToolErrorCategory.BUSINESS_LOGIC:
        return (
            f"业务逻辑错误：{error_str}。"
            f"可能原因：1) 前置条件未满足 2) 输入数据不符合业务规则 3) 策略/模型配置不正确。"
        )

    if category == ToolErrorCategory.TIMEOUT:
        return f"工具 {tool_name} 执行超时（60秒）。可能原因：查询范围过大、资产数量过多或系统负载较高。"

    if category == ToolErrorCategory.NOT_FOUND:
        return f"资源不存在：{error_str}。请使用 query_assets 等查询工具确认资产代码/模型 ID 是否正确。"

    if category == ToolErrorCategory.DEPENDENCY_MISSING:
        return f"前置工具未执行：{error_str}。请先调用所需的前置工具获取必要数据后再重试。"

    if category == ToolErrorCategory.SYSTEM_ERROR:
        return f"系统错误：{error_str}。可能是网络波动或服务暂时不可用。"

    return f"未知错误：{error_str}"


def generate_recovery_suggestion(category: ToolErrorCategory, tool_name: str) -> str:
    """根据错误类型生成恢复建议"""
    suggestions = {
        ToolErrorCategory.PARAMETER_ERROR: (
            "1) 检查参数格式是否正确 2) 参考工具 schema 说明 3) 简化参数后重试"
        ),
        ToolErrorCategory.BUSINESS_LOGIC: (
            "1) 检查前置条件是否满足 2) 确认输入数据是否正确 3) 尝试用查询工具先验证"
        ),
        ToolErrorCategory.TIMEOUT: (
            "1) 缩小查询范围（如缩短时间段） 2) 减少资产数量 3) 分多次调用"
        ),
        ToolErrorCategory.NOT_FOUND: (
            "1) 使用 query_assets 确认资产代码 2) 检查拼写和大小写 3) 确认数据是否存在"
        ),
        ToolErrorCategory.DEPENDENCY_MISSING: (
            "1) 按工具依赖顺序调用 2) 先执行前置工具获取必要数据"
        ),
        ToolErrorCategory.SYSTEM_ERROR: (
            "1) 等待片刻后重试 2) 使用其他工具达成相同目标"
        ),
    }
    return suggestions.get(category, "请检查错误信息并调整策略")



# ======================================================================
# LLM 请求层面的错误分类
# 用于对 LLM API 调用过程中的异常（如限流、超时、认证等）进行分类，
# 与上方 ToolErrorCategory（工具执行层面）并列使用。
# ======================================================================

class ErrorCategory(Enum):
    """错误分类枚举（LLM 请求层面）"""
    RATE_LIMIT = "rate_limit"         # 429 限流 → 指数退避重试
    CONTEXT_LENGTH = "context_length" # 上下文超长 → 截断后重试（未来配合上下文压缩引擎）
    TOOL_FAILURE = "tool_failure"     # 保留：预留给未来 LLM 层面的工具调用格式错误（如 function_call JSON 解析失败）
    AUTH_ERROR = "auth_error"         # 401/403 认证失败 → 中止
    NETWORK = "network"              # 超时/连接失败 → 短暂重试
    FATAL = "fatal"                  # 不可恢复 → 中止并返回用户友好错误


@dataclass
class HandleResult:
    """错误处理结果"""
    retry: bool                       # 是否应该重试
    action: str = "none"             # 附加动作: "compress" / "switch_model" / "none"
    wait_seconds: float = 0          # 重试前等待时间（秒）
    user_message: str = ""           # 面向用户的友好错误说明


class ErrorHandler:
    """
    错误分类与重试处理器

    分类管道优先级：
    1. HTTP 状态码: 401→auth, 429→rate_limit, 402→消歧, 500/502/503→network
    2. 异常类型: TimeoutError/ConnectionError→network
    3. 错误消息模式: "context length"→context_length
    4. 兜底: →FATAL（不盲目重试）

    安全约束：
    - 日志不记录完整 API Key（仅后 4 位）
    - 重试硬限 3 次
    - 退避最长 30 秒
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ):
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------
    def classify(self, error: Exception) -> ErrorCategory:
        """
        将异常分类为 ErrorCategory

        分类管道（按优先级）:
        1. 检查 HTTP 状态码（openai SDK 的 APIStatusError）
        2. 检查异常类型（超时、连接等）
        3. 检查错误消息关键词
        4. 兜底分类
        """
        # 1. HTTP 状态码判断
        status_code = self._extract_status_code(error)
        if status_code:
            if status_code in (401, 403):
                return ErrorCategory.AUTH_ERROR
            if status_code == 429:
                return ErrorCategory.RATE_LIMIT
            if status_code == 402:
                # 消歧：billing vs rate_limit
                return self._disambiguate_402(error)
            if status_code in (500, 502, 503, 529):
                return ErrorCategory.NETWORK

        # 2. 异常类型判断
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            return ErrorCategory.NETWORK
        if isinstance(error, (ConnectionError, OSError)):
            return ErrorCategory.NETWORK

        # 3. 错误消息关键词匹配
        error_msg = str(error).lower()
        if any(kw in error_msg for kw in (
            "context length", "maximum context", "too many tokens",
            "max_tokens", "context_length_exceeded",
        )):
            return ErrorCategory.CONTEXT_LENGTH
        if "rate limit" in error_msg or "rate_limit" in error_msg or "overload" in error_msg:
            return ErrorCategory.RATE_LIMIT
        if any(kw in error_msg for kw in (
            "authentication", "api key", "unauthorized", "invalid_api_key",
        )):
            return ErrorCategory.AUTH_ERROR
        if any(kw in error_msg for kw in (
            "timeout", "timed out", "connection", "connect",
        )):
            return ErrorCategory.NETWORK

        # 4. 兜底
        return ErrorCategory.FATAL

    # ------------------------------------------------------------------
    # 处理
    # ------------------------------------------------------------------
    async def handle(self, error: Exception, retry_count: int) -> HandleResult:
        """
        根据错误分类和重试次数决定处理策略
        """
        category = self.classify(error)
        safe_msg = self.sanitize_error_message(str(error))
        logger.warning(
            "[ErrorHandler] 错误分类: {} | 重试次数: {} | 错误: {}",
            category.value, retry_count, safe_msg,
        )

        # 超过最大重试次数
        if retry_count >= self.max_retries:
            return HandleResult(
                retry=False,
                user_message=f"多次重试后仍然失败（{category.value}），请稍后再试。",
            )

        if category == ErrorCategory.RATE_LIMIT:
            # 引擎过载时使用更大的退避基数（overloaded 恢复慢）
            error_msg_lower = str(error).lower()
            if "overload" in error_msg_lower:
                wait = min(self.base_backoff * (3 ** (retry_count + 1)), self.max_backoff)
            else:
                wait = self._calculate_backoff(retry_count)
            return HandleResult(
                retry=True,
                wait_seconds=wait,
                user_message="API 请求频率受限，正在等待重试...",
            )

        if category == ErrorCategory.CONTEXT_LENGTH:
            return HandleResult(
                retry=True,
                action="compress",
                user_message="对话上下文过长，正在压缩后重试...",
            )

        if category == ErrorCategory.NETWORK:
            wait = self._calculate_backoff(retry_count)
            return HandleResult(
                retry=True,
                wait_seconds=wait,
                user_message="网络连接不稳定，正在重试...",
            )

        if category == ErrorCategory.AUTH_ERROR:
            return HandleResult(
                retry=False,
                user_message="API 认证失败，请检查配置。",
            )

        if category == ErrorCategory.TOOL_FAILURE:
            return HandleResult(
                retry=False,
                action="none",
                user_message="工具执行失败。",
            )

        # FATAL
        return HandleResult(
            retry=False,
            user_message="发生不可恢复的错误，请稍后重试。",
        )

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------
    def _extract_status_code(self, error: Exception) -> int | None:
        """从异常中提取 HTTP 状态码"""
        # openai SDK: APIStatusError 有 status_code 属性
        if hasattr(error, "status_code"):
            return error.status_code
        # httpx: Response 有 status_code
        if hasattr(error, "response") and hasattr(error.response, "status_code"):
            return error.response.status_code
        # 递归检查 __cause__
        if error.__cause__:
            return self._extract_status_code(error.__cause__)
        return None

    def _disambiguate_402(self, error: Exception) -> ErrorCategory:
        """402 消歧: billing vs rate_limit"""
        msg = str(error).lower()
        transient_signals = ["try again", "retry", "resets at", "periodic", "window"]
        if any(s in msg for s in transient_signals):
            return ErrorCategory.RATE_LIMIT
        return ErrorCategory.AUTH_ERROR  # 默认当作 billing/auth 问题

    def _calculate_backoff(self, retry_count: int) -> float:
        """计算指数退避时间"""
        return min(self.base_backoff * (2 ** retry_count), self.max_backoff)

    @staticmethod
    def sanitize_error_message(msg: str) -> str:
        """清理错误消息，隐藏敏感信息（如 API Key）"""
        # 隐藏看起来像 API Key 的字符串
        sanitized = re.sub(
            r"(sk-|key-|api-)[a-zA-Z0-9]{4,}",
            lambda m: m.group()[:6] + "****",
            msg,
        )
        # 隐藏 Bearer token
        sanitized = re.sub(r"Bearer\s+[a-zA-Z0-9._-]+", "Bearer ****", sanitized)
        return sanitized

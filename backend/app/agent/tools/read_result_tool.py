"""
回读完整工具结果

当工具结果因预算管控被截断时，Agent 可通过此工具按需回读完整数据。
result_id 在截断提示中给出，对应 MongoDB agent_tool_results 集合中的记录。
"""
from loguru import logger

from app.agent.tools.base import BaseTool
from app.config.database import Database


class ReadToolResultTool(BaseTool):
    """回读被预算管控截断的完整工具结果"""

    name = "read_tool_result"
    description = (
        "回读之前被截断的工具调用完整结果。"
        "当工具返回提示'结果已截断'并给出 result_id 时，"
        "调用此工具传入该 result_id 获取完整数据。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "result_id": {
                "type": "string",
                "description": "工具结果 ID（在截断提示中给出）",
            },
        },
        "required": ["result_id"],
    }

    # 回读结果本身也需要限制，避免循环膨胀
    max_result_chars = 25000
    budget_threshold = 0  # 回读结果不再二次持久化

    async def execute(self, result_id: str, **kwargs) -> dict:
        """从 MongoDB agent_tool_results 集合读取完整结果"""
        if not result_id or not isinstance(result_id, str):
            return {"success": False, "error": "缺少有效的 result_id 参数"}

        try:
            db = Database.get_database()
            from app.config.collections import COL_AGENT_TOOL_RESULTS
            coll = db[COL_AGENT_TOOL_RESULTS]
            doc = await coll.find_one({"message_id": result_id})

            if not doc:
                return {
                    "success": False,
                    "error": f"未找到 result_id='{result_id}' 对应的完整结果（可能已过期，30天TTL）",
                }

            full_result = doc.get("full_result", "")
            tool_name = doc.get("tool_name", "unknown")
            logger.info(
                "[ReadToolResult] 回读成功: result_id={}, tool={}, 长度={}",
                result_id, tool_name, len(full_result),
            )

            return {
                "success": True,
                "tool_name": tool_name,
                "result_id": result_id,
                "full_result": full_result,
            }
        except Exception as e:
            logger.exception("[ReadToolResult] 回读失败: result_id={}", result_id)
            return {"success": False, "error": f"回读失败: {str(e)}"}

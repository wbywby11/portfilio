"""
监控域工具 — query_monitors（读）+ update_monitor_config（写，需确认）

query_monitors action:
- list：监控策略列表（名称/来源/状态/资产数）
- report：监控日报（指定 monitor_id，默认最新一期；可传 date 查历史）

update_monitor_config：修改监控条目安全字段（名称/状态/描述），
受 M2 护栏约束：仅允许修改 agent 创建的监控条目。

复用链路：MonitoredStrategyService（监控条目）+ MonitorService(MonitorQueryMixin)（日报）
"""
from app.agent.core.write_guard import assert_agent_owned
from app.agent.tools._helpers import bson_safe
from app.agent.tools.base import BaseTool, ConfirmableTool

# 日报文档中体积大且对问答无用的字段（剔除以控制上下文）
_REPORT_DROP_KEYS = {"_id", "nav_curve", "weight_history", "event_log"}


class QueryMonitorsTool(BaseTool):
    """监控查询工具"""

    name = "query_monitors"
    description = (
        "查询策略监控信息。两种模式：\n"
        "1) action=list：列出监控中的策略（名称/来源类型/状态/资产数量）\n"
        "2) action=report：查监控日报（传 monitor_id）——默认返回最新一期日报，"
        "含净值、权重、风险指标；传 date（YYYY-MM-DD）查历史日报"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "report"],
                "description": "查询模式",
            },
            "monitor_id": {
                "type": "string",
                "description": "report 模式的监控条目 ID（必填，来自 action=list 的 id 字段）",
            },
            "date": {
                "type": "string",
                "description": "report 模式查指定日期日报（YYYY-MM-DD，可选，默认最新）",
            },
            "include_archived": {
                "type": "boolean",
                "description": "list 模式是否包含已归档条目（默认 false）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 10000

    async def execute(
        self,
        action: str = "list",
        monitor_id: str = "",
        date: str = "",
        include_archived: bool = False,
        **kwargs,
    ) -> dict:
        if action == "list":
            return await self._list(include_archived)
        if action == "report":
            if not monitor_id:
                return {"success": False, "error": "report 模式需要 monitor_id（先用 action=list 获取）"}
            return await self._report(monitor_id, date)
        return {"success": False, "error": f"未知 action: {action}（可选 list/report）"}

    # ------------------------------------------------------------------

    async def _list(self, include_archived: bool) -> dict:
        from app.services.monitored_strategy_service import MonitoredStrategyService

        docs = await MonitoredStrategyService().list(status=None if not include_archived else None)
        if include_archived:
            # list() 默认排除 archived；需要归档条目时直查集合
            docs = await MonitoredStrategyService().collection.find({}).sort("created_at", 1).to_list(length=200)

        records = []
        for doc in docs:
            records.append({
                "id": str(doc.get("_id", "")),
                "display_name": doc.get("display_name", ""),
                "source_type": doc.get("source_type", ""),
                "source_ref": doc.get("source_ref", ""),
                "status": doc.get("status", ""),
                "asset_count": len(doc.get("asset_codes") or []),
                "description": (doc.get("description") or "")[:120],
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": f"共 {len(records)} 个监控条目。" if records else "暂无监控条目。",
            "hint": "使用 action=report 并传 monitor_id（即上方 id）可查看监控日报",
        }

    async def _report(self, monitor_id: str, date: str) -> dict:
        from app.services.monitor_service import MonitorService

        service = MonitorService()
        if date:
            report = await service.get_daily_report(monitor_id, date)
            if not report:
                return {"success": False, "error": f"未找到 {monitor_id} 在 {date} 的日报"}
        else:
            reports = await service.get_report_list(monitor_id, skip=0, limit=1)
            if not reports:
                return {"success": False, "error": f"监控条目 {monitor_id} 暂无日报数据"}
            report = reports[0]

        # 剔除大字段，其余原样返回（日报结构随监控引擎演进，不做硬编码字段假设）
        trimmed = {k: v for k, v in report.items() if k not in _REPORT_DROP_KEYS}

        return {
            "success": True,
            "count": 1,
            "data": {"records": [bson_safe(trimmed)]},
            "metadata": {"record_count": 1, "monitor_id": monitor_id, "date": report.get("date", "")},
            "summary": f"监控日报（{report.get('date', '未知日期')}）已返回，字段含义见文档内各键名。",
        }


class UpdateMonitorConfigTool(ConfirmableTool):
    """修改监控条目配置（两阶段确认 + M2 护栏）"""

    name = "update_monitor_config"
    description = (
        "修改监控条目配置（写操作，需用户确认后执行）。"
        "仅支持安全字段：display_name（显示名称）、status（active/paused/archived）、"
        "description（描述）。策略参数类配置（目标波动/重置阈值等）请到策略编辑页修改。"
        "仅允许修改 agent 创建的监控条目，用户手动创建的会被拒绝。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "monitor_id": {
                "type": "string",
                "description": "监控条目 ID（来自 query_monitors 的 id 字段）",
            },
            "display_name": {
                "type": "string",
                "description": "新显示名称（可选）",
            },
            "status": {
                "type": "string",
                "enum": ["active", "paused", "archived"],
                "description": "新状态（可选）",
            },
            "description": {
                "type": "string",
                "description": "新描述（可选）",
            },
        },
        "required": ["monitor_id"],
    }

    def build_preview(self, arguments: dict) -> dict:
        return {
            "tool": self.name,
            "operation": "修改监控配置",
            "target": arguments.get("monitor_id", ""),
            "arguments": {k: v for k, v in arguments.items() if v not in (None, "")},
        }

    async def perform(self, **kwargs) -> dict:
        from app.services.monitored_strategy_service import MonitoredStrategyService

        monitor_id = kwargs.get("monitor_id", "")
        updates = {
            k: kwargs.get(k)
            for k in ("display_name", "status", "description")
            if kwargs.get(k) not in (None, "")
        }
        if not monitor_id:
            return {"success": False, "error": "缺少 monitor_id"}
        if not updates:
            return {"success": False, "error": "未提供任何待修改字段（display_name/status/description）"}

        service = MonitoredStrategyService()
        doc = await service.get(monitor_id)
        # M2 护栏：非 agent 创建的监控条目拒绝修改（抛 WriteGuardError 转 rejected）
        assert_agent_owned(doc, "监控条目", page_hint="策略监控页面")

        ok = await service.update(monitor_id, updates)
        if not ok:
            return {"success": False, "error": "更新未生效，请检查字段值"}
        return {
            "success": True,
            "monitor_id": monitor_id,
            "updated_fields": list(updates.keys()),
            "summary": f"监控配置已更新：{', '.join(updates.keys())}。",
        }

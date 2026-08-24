"""
策略域读工具 — query_strategies

action:
- list：策略模板清单（注册表元数据：内置 + 动态策略）
- detail：单个策略模板详情（描述/composition/参数 Schema）或配置实例详情（传 model_id）
- filter：已配置策略实例查询（COL_STRATEGY_MODELS，支持 template_code/status 过滤）

复用链路：ModelTemplateService（模板注册表）+ StrategyModelService.collection（配置实例）
"""
from app.agent.tools._helpers import fmt_datetime, pct
from app.agent.tools.base import BaseTool


class QueryStrategiesTool(BaseTool):
    """策略查询工具 — 模板注册表 + 配置实例"""

    name = "query_strategies"
    description = (
        "查询策略相关信息。三种模式：\n"
        "1) action=list：列出所有可用策略模板（策略类型注册表，含名称/描述/分类）\n"
        "2) action=detail：查单个策略详情——传 template_code 返回该策略类型的描述、"
        "三层组合结构与参数 Schema（可配置参数清单）；传 model_id 返回该配置实例的完整参数\n"
        "3) action=filter：查询已配置的策略实例列表（可按 template_code/status 过滤），"
        "含最近一次回测的四指标摘要"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "detail", "filter"],
                "description": "查询模式",
            },
            "template_code": {
                "type": "string",
                "description": "策略模板代码（detail 模式查模板详情 / filter 模式按模板过滤，如 risk_parity）",
            },
            "model_id": {
                "type": "string",
                "description": "策略配置实例 ID（detail 模式查实例详情）",
            },
            "status": {
                "type": "string",
                "description": "filter 模式按状态过滤（可选）",
            },
            "include_portfolio": {
                "type": "boolean",
                "description": "filter 模式是否包含组合模型（默认 false）",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限（默认 20，最大 50）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 8000

    async def execute(
        self,
        action: str = "list",
        template_code: str = "",
        model_id: str = "",
        status: str = "",
        include_portfolio: bool = False,
        limit: int = 20,
        **kwargs,
    ) -> dict:
        if action == "list":
            return await self._list_templates()
        if action == "detail":
            if model_id:
                return await self._model_detail(model_id)
            if template_code:
                return await self._template_detail(template_code)
            return {"success": False, "error": "detail 模式需要 template_code 或 model_id"}
        if action == "filter":
            return await self._filter_models(template_code, status, include_portfolio, limit)
        return {"success": False, "error": f"未知 action: {action}（可选 list/detail/filter）"}

    # ------------------------------------------------------------------

    async def _list_templates(self) -> dict:
        from app.services.model_template_service import ModelTemplateService

        templates = await ModelTemplateService().list_templates(is_active=True, limit=100)
        items = [{
            "code": t.code,
            "name": t.name,
            "description": t.description,
            "category": t.category or "allocation",
            "is_builtin": t.is_builtin,
            "param_count": len(t.parameters or []),
        } for t in templates]
        return {
            "success": True,
            "count": len(items),
            "templates": items,
            "hint": "使用 action=detail 并传 template_code 可查看某策略的参数 Schema",
        }

    async def _template_detail(self, template_code: str) -> dict:
        from app.services.model_template_service import ModelTemplateService
        from app.services.strategy_model_service import StrategyModelService

        template = await ModelTemplateService().get_template_by_code(template_code)
        if not template:
            return {"success": False, "error": f"未找到策略模板: {template_code}，请先用 action=list 查看可用模板"}

        model_service = StrategyModelService()
        instance_count = await model_service.collection.count_documents(
            {"template_code": template_code}
        )

        return {
            "success": True,
            "template": {
                "code": template.code,
                "name": template.name,
                "description": template.description,
                "category": template.category or "allocation",
                "composition": template.composition or {},
                "is_builtin": template.is_builtin,
                "param_schema": template.param_schema,
            },
            "configured_instance_count": instance_count,
            "hint": "param_schema 中每个参数含 name/label/type/default/description；"
                    "使用 action=filter 并传 template_code 可查看该模板的已配置实例",
        }

    async def _model_detail(self, model_id: str) -> dict:
        from app.services.strategy_model_service import StrategyModelService

        try:
            model = await StrategyModelService().get_model(model_id)
        except Exception:
            return {"success": False, "error": f"无效的 model_id: {model_id}"}
        if not model:
            return {"success": False, "error": f"未找到策略配置实例: {model_id}"}

        data = model.dict(by_alias=True, exclude_none=True)
        data.pop("id", None)
        return {
            "success": True,
            "model_id": model_id,
            "model": data,
        }

    async def _filter_models(
        self, template_code: str, status: str, include_portfolio: bool, limit: int,
    ) -> dict:
        from app.services.strategy_model_service import StrategyModelService

        limit = max(1, min(int(limit or 20), 50))
        collection = StrategyModelService().collection

        query: dict = {}
        if not include_portfolio:
            query["is_portfolio"] = {"$ne": True}
        if template_code:
            query["template_code"] = template_code
        if status:
            query["status"] = status

        projection = {
            "name": 1, "template_code": 1, "status": 1, "rebalance_frequency": 1,
            "asset_codes": 1, "latest_backtest_summary": 1,
            "created_by": 1, "is_portfolio": 1, "created_at": 1, "updated_at": 1,
        }
        records = []
        cursor = collection.find(query, projection).sort("updated_at", -1).limit(limit)
        async for doc in cursor:
            summary = doc.get("latest_backtest_summary") or {}
            records.append({
                "id": str(doc["_id"]),
                "name": doc.get("name", ""),
                "template_code": doc.get("template_code", ""),
                "status": doc.get("status", ""),
                "is_portfolio": bool(doc.get("is_portfolio")),
                "rebalance_frequency": doc.get("rebalance_frequency", ""),
                "asset_count": len(doc.get("asset_codes") or []),
                "annual_return_pct": pct(summary.get("annual_return")),
                "annual_vol_pct": pct(summary.get("annual_vol")),
                "sharpe": summary.get("sharpe"),
                "max_drawdown_pct": pct(summary.get("max_drawdown")),
                "last_backtest_date": (summary.get("backtest_date") or "")[:10],
                "created_by": doc.get("created_by", "user"),
                "updated_at": fmt_datetime(doc.get("updated_at")),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": (
                f"共查到 {len(records)} 个策略配置实例"
                + (f"（模板={template_code}）" if template_code else "")
                + "。四指标为最近一次回测结果（年化收益/波动为百分比，sharpe 为比率）。"
                if records else "未查到符合条件的策略配置实例。"
            ),
            "hint": "使用 action=detail 并传 model_id 可查看实例完整参数",
        }

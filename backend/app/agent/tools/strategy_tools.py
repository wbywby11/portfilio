"""
策略域工具 — query_strategies（读）+ create_strategy_model（写，需确认）

query_strategies action:
- list：策略模板清单（注册表元数据：内置 + 动态策略）
- detail：单个策略模板详情（描述/composition/参数 Schema）或配置实例详情（传 model_id）
- filter：已配置策略实例查询（COL_STRATEGY_MODELS，支持 template_code/status 过滤）

写工具边界：create_strategy_model 新建实例自动打标 created_by=agent；
template_code 必须在模板注册表内，防止 LLM 编造不存在的策略类型。

复用链路：ModelTemplateService（模板注册表）+ StrategyModelService（CRUD + 参数净化）
"""
from bson import ObjectId

from app.agent.core.write_guard import AGENT_CREATED_BY, stamp_agent_origin
from app.agent.tools._helpers import fmt_datetime, pct
from app.agent.tools.base import BaseTool, ConfirmableTool
from app.allocation.runtime_params import MANUAL_ALLOCATION_TEMPLATE_CODES

# 主观固定权重模板 code（含历史名）：与保存侧固化分支同源，不再各写一份
_MANUAL_ALLOCATION_TEMPLATE_CODES = MANUAL_ALLOCATION_TEMPLATE_CODES
_REBALANCE_FREQUENCIES = ("日", "周", "月", "季", "年", "自定义")


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


class CreateStrategyModelTool(ConfirmableTool):
    """创建策略模型实例（两阶段确认，新建实体自动打 agent 标记）"""

    name = "create_strategy_model"
    description = (
        "创建策略模型实例（写操作，需用户确认后执行）。"
        "template_code 必须是系统已有模板（可用 query_strategies action=list 查看，"
        "如 risk_parity/mean_variance/manual_allocation），并用 action=detail 查参数 Schema。"
        "用户使用行业术语/口语表述策略类型时，先检索知识库确认对应的系统模板与参数约定。"
        "主观固定权重类需求（如行业固定比例组合）用 manual_allocation 模板，"
        "并在 parameters.manual_weights 中指定 {asset_code: weight}，权重总和为 1。"
        "行业口语/别名到模板的映射规则见知识库《业务术语表》。"
        "创建的模型标记为 agent 创建，可用 run_backtest 回测。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "模型名称",
            },
            "template_code": {
                "type": "string",
                "description": "策略模板代码（如 risk_parity / manual_allocation）",
            },
            "asset_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "底层资产代码列表",
            },
            "rebalance_frequency": {
                "type": "string",
                "enum": list(_REBALANCE_FREQUENCIES),
                "description": "调仓频率（默认 月）",
            },
            "parameters": {
                "type": "object",
                "description": "模板参数（按 param_schema 填写，不传则用模板默认值；"
                               "manual_allocation 必传 manual_weights）",
            },
            "description": {
                "type": "string",
                "description": "模型描述（可选）",
            },
        },
        "required": ["name", "template_code", "asset_codes"],
    }

    tool_timeout = 90.0

    async def execute(self, **kwargs) -> dict:
        error = self._validate(kwargs)
        if error:
            return {"success": False, "error": error}
        return await super().execute(**kwargs)

    def build_preview(self, arguments: dict) -> dict:
        return {
            "tool": self.name,
            "operation": "创建策略模型",
            "target": arguments.get("name", ""),
            "arguments": arguments,
        }

    async def perform(self, **kwargs) -> dict:
        from app.models.strategy_model import StrategyModel
        from app.services.asset_service import AssetService
        from app.services.model_template_service import ModelTemplateService
        from app.services.strategy_model_service import StrategyModelService

        error = self._validate(kwargs)
        if error:
            return {"success": False, "error": error}

        conversation_id = kwargs.get("conversation_id", "")
        name = kwargs["name"].strip()
        template_code = kwargs["template_code"].strip()
        asset_codes = [str(c).strip() for c in kwargs["asset_codes"] if str(c).strip()]
        parameters = dict(kwargs.get("parameters") or {})

        # 护栏 1：template_code 必须在模板注册表内（防 LLM 编造）
        template = await ModelTemplateService().get_template_by_code(template_code)
        if not template:
            return {
                "success": False,
                "error": f"策略模板不存在: {template_code}。请先用 query_strategies action=list 查看可用模板。",
            }

        # 护栏 2：资产代码必须存在于 assets 集合
        asset_service = AssetService()
        name_map: dict[str, str] = {}
        cursor = asset_service.collection.find({"code": {"$in": asset_codes}}, {"code": 1, "name": 1})
        async for asset_doc in cursor:
            name_map[asset_doc.get("code", "")] = asset_doc.get("name", "")
        unknown = [c for c in asset_codes if c not in name_map]
        if unknown:
            return {"success": False, "error": f"以下资产代码不存在: {', '.join(unknown)}"}

        # 护栏 3：manual_allocation 的固定权重必须覆盖全部资产且总和为 1
        if template_code in _MANUAL_ALLOCATION_TEMPLATE_CODES:
            mw = parameters.get("manual_weights")
            if not isinstance(mw, dict) or not mw:
                return {
                    "success": False,
                    "error": "manual_allocation 模板必须在 parameters.manual_weights 中指定 {asset_code: weight}",
                }
            extra = [c for c in mw if c not in asset_codes]
            if extra:
                return {"success": False, "error": f"manual_weights 含资产池外的代码: {', '.join(extra)}"}
            missing = [c for c in asset_codes if c not in mw]
            if missing:
                return {"success": False, "error": f"manual_weights 缺少资产的权重: {', '.join(missing)}"}
            total = sum(float(v) for v in mw.values())
            if abs(total - 1.0) > 0.01:
                return {"success": False, "error": f"manual_weights 权重总和必须为 1，当前: {total:.4f}"}

        model = StrategyModel(
            name=name,
            template_code=template_code,
            description=kwargs.get("description") or None,
            asset_codes=asset_codes,
            asset_names={c: name_map[c] for c in asset_codes if name_map.get(c)},
            parameters=parameters,
            rebalance_frequency=kwargs.get("rebalance_frequency") or "月",
            created_by=AGENT_CREATED_BY,
        )
        service = StrategyModelService()
        model_id = await service.create_model(model)

        # 补打 agent_meta（StrategyModel 模型不承载该字段，直接写文档）
        meta_doc = stamp_agent_origin({}, conversation_id=conversation_id, tool_name=self.name)
        await service.collection.update_one(
            {"_id": ObjectId(model_id)}, {"$set": {"agent_meta": meta_doc["agent_meta"]}},
        )

        return {
            "success": True,
            "model_id": model_id,
            "name": name,
            "template_code": template_code,
            "asset_codes": asset_codes,
            "summary": (
                f"策略模型「{name}」创建成功（模板={template_code}，"
                f"底层资产 {len(asset_codes)} 个）。可用 run_backtest 对该 model_id 发起回测。"
            ),
        }

    @staticmethod
    def _validate(kwargs: dict) -> str:
        if not kwargs.get("name", "").strip():
            return "缺少模型名称"
        if not kwargs.get("template_code", "").strip():
            return "缺少 template_code"
        asset_codes = kwargs.get("asset_codes") or []
        if not isinstance(asset_codes, list) or not asset_codes:
            return "asset_codes 不能为空"
        if len(set(str(c).strip() for c in asset_codes)) != len(asset_codes):
            return "asset_codes 存在重复"
        freq = kwargs.get("rebalance_frequency") or "月"
        if freq not in _REBALANCE_FREQUENCIES:
            return f"rebalance_frequency 无效: {freq}（可选 {'/'.join(_REBALANCE_FREQUENCIES)}）"
        return ""

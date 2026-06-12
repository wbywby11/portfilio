"""
对话服务 - 编排 Agent 与对话存储
"""
import asyncio
import json
import uuid
from pathlib import Path

from loguru import logger

from app.agent.core.agent import InvestmentAgent
from app.agent.core.config import get_agent_settings, get_model_configs
from app.agent.core.context_engine import ContextEngine
from app.agent.core.error_handler import ErrorHandler
from app.agent.core.model_router import ModelRouter
from app.agent.prompts.system_prompts import get_system_prompt
from app.agent.schemas.agent_schemas import AgentReply
from app.agent.services.attachment_service import AttachmentService
from app.agent.services.conversation_store import ConversationStore
from app.agent.services.data_context import DataContext
from app.agent.tools.base import tool_registry, ToolRegistry
from app.agent.memory import MemoryManager
from app.agent.core.plan_manager import PlanManager, PlanStep, ExecutionPlan, StepStatus

# 全局单例（原来在 tools/__init__.py 中，现在直接在此创建）
_memory_manager = MemoryManager()
_plan_manager = PlanManager()
from app.agent.skills import SkillLoader, SkillSelector


# 项目根目录推算
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ToolResultTracker:
    """在工具执行时增量收集报告所需的关键数据点，避免报告生成时全量扫描历史消息"""

    TRACKED_TOOLS = [
        "query_assets", "search_assets",
        "recommend_strategy", "compare_strategies",
        "compute_weights", "run_backtest", "risk_assessment",
        "execute_backtest", "create_strategy_model",
    ]

    # 每个工具结果中需要提取的关键字段
    EXTRACT_KEYS = {
        "query_assets": ["assets", "total_count", "summary"],
        "search_assets": ["assets", "total_count"],
        "recommend_strategy": ["strategy_name", "strategy_type", "recommendation", "summary", "recommended", "candidates"],
        "compare_strategies": ["comparison_table", "recommendation", "summary", "results", "conclusion"],
        "compute_weights": ["weights", "strategy_name", "rebalance_date", "summary"],
        "run_backtest": ["performance_summary", "metrics", "strategy_name", "status"],
        "execute_backtest": ["performance_summary", "metrics", "strategy_name", "status", "results"],
        "risk_assessment": ["risk_level", "risk_factors", "summary"],
        "create_strategy_model": ["strategy_type", "rebalance_frequency", "lookback_days", "params"],
    }

    def __init__(self):
        self._tracked_data: dict[str, list[dict]] = {}

    def track(self, tool_name: str, result: str | dict):
        """提取并缓存报告所需的关键字段"""
        if tool_name not in self.TRACKED_TOOLS:
            return

        # 解析结果
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                data = {"raw_summary": result[:500]}
        else:
            data = result

        # 提取关键字段
        extract_keys = self.EXTRACT_KEYS.get(tool_name, ["summary"])
        extracted = {"tool_name": tool_name}

        if isinstance(data, dict):
            # 支持嵌套 data 字段
            inner = data.get("data", data)
            source = inner if isinstance(inner, dict) else data
            for key in extract_keys:
                if key in source:
                    value = source[key]
                    # 列表类字段只保留前5条
                    if isinstance(value, list) and len(value) > 5:
                        extracted[key] = value[:5]
                        extracted[f"_{key}_total"] = len(value)
                    else:
                        extracted[key] = value
            # 始终保留 success/error 状态
            if "success" in data:
                extracted["success"] = data["success"]
            if "error" in data:
                extracted["error"] = data["error"]

        if tool_name not in self._tracked_data:
            self._tracked_data[tool_name] = []
        self._tracked_data[tool_name].append(extracted)

    def get_report_context(self, max_chars: int = 8000) -> dict:
        """获取报告所需的精简上下文数据，限制在指定字符数内"""
        context = {
            "tracked_tools_summary": {},
            "asset_names": [],
            "recommended_strategy": None,
            "backtest_results": None,
        }

        # 提取资产名称
        for item in self._tracked_data.get("query_assets", []) + self._tracked_data.get("search_assets", []):
            if "assets" in item and isinstance(item["assets"], list):
                for asset in item["assets"][:10]:
                    name = asset.get("name") or asset.get("asset_name", "")
                    if name and name not in context["asset_names"]:
                        context["asset_names"].append(name)

        # 提取推荐策略
        for item in self._tracked_data.get("recommend_strategy", []):
            if "strategy_name" in item:
                context["recommended_strategy"] = item.get("strategy_name")
            elif "recommended" in item:
                context["recommended_strategy"] = item.get("recommended")

        # 提取回测结果
        for item in self._tracked_data.get("run_backtest", []) + self._tracked_data.get("execute_backtest", []):
            context["backtest_results"] = item.get("performance_summary")

        # 各工具精简摘要
        for tool_name, items in self._tracked_data.items():
            context["tracked_tools_summary"][tool_name] = {
                "call_count": len(items),
                "latest_result": items[-1] if items else None,
            }

        # 控制总大小
        result_str = json.dumps(context, ensure_ascii=False, default=str)
        if len(result_str) > max_chars:
            # 逐步削减数据量
            context.pop("tracked_tools_summary", None)
            result_str = json.dumps(context, ensure_ascii=False, default=str)

        return context

    def get_tool_results_for_report(self) -> dict[str, list[dict]]:
        """获取与 _extract_tool_results 兼容的数据格式，供报告工具直接使用"""
        return dict(self._tracked_data)

    def has_data(self) -> bool:
        return bool(self._tracked_data)

    def clear(self):
        self._tracked_data.clear()


# 字段中文映射（用于 join_path 语义化描述）
_FIELD_ZH_MAP: dict[str, str] = {
    "ISR_ID": "机构/发行人ID", "ISR_NM": "机构名称", "ISRS_TYPE": "机构类型",
    "AST_CD": "证券代码", "AST_NM": "证券名称", "AST_TYPE": "资产大类",
    "PORT_ID": "产品/组合ID", "PORT_NM": "产品名称", "PORT_TYPE": "产品类型",
    "BIZ_DT": "业务日期", "TRADE_ID": "交易编号", "ORDER_ID": "委托编号",
    "CUSTOMER_ID": "客户ID", "CUST_NM": "客户名称", "CUST_TYPE": "客户类型",
    "SELLER_ID": "销售人员ID", "CHANNEL": "渠道",
    "subject_name": "主体名称", "subject_type": "主体类型",
    "risk_id": "风险事件ID", "risk_signal_level": "风险信号等级",
    "biz_date": "业务日期", "rule_large": "规则大类",
    "SRC_ISR_ID": "源机构ID", "TGT_ISR_ID": "目标机构ID",
    "REL_TYPE": "关联类型", "PARTY_ID": "参与方ID", "PARTY_NM": "参与方名称",
    "PARTY_ROLE": "参与方角色", "WEIGHT": "持仓权重", "HLD_QTY": "持仓数量",
    "MKT_VAL": "市值", "HLD_SHR": "持股比例", "HLD_AMT": "持有金额",
    "EXPOSURE": "风险敲口", "VAR_99": "99%VaR", "LIMIT_FLAG": "限额标识",
    "UNREAL_PNL": "浮动盈亏", "INTERNAL_RATING": "内部评级", "EXT_RATING": "外部评级",
    "PD_1Y": "1年违约概率", "LGD": "违约损失率", "EXPECTED_LOSS": "预期损失",
    "RISK_LVL": "风险等级", "RISK_SCORE": "风险评分",
    "AUM": "管理规模", "BENCHMARK": "业绩基准", "ESTAB_DT": "成立日期", "STATUS": "状态",
    "COST_AMT": "成本金额", "TRADE_AMT": "交易金额", "TRADE_PRC": "交易价格",
    "MATURITY_DT": "到期日", "COUPON_RATE": "票面利率", "MARKET": "上市市场",
    "RATING": "信用评级", "ISSUE_AMT": "发行规模", "CCY": "币种",
    "CLOSE_PRC": "收盘价", "YTM": "到期收益率", "DURATION": "久期",
}

# 表名中文映射（用于 join_path 语义描述）
_TABLE_ZH_MAP: dict[str, str] = {
    "subject_risk_records": "主体观点风险记录表",
    "dwd_isr_institution": "机构主表",
    "dwd_ptl_ast_hld": "产品持仓明细",
    "dwd_ptl_info": "产品主表",
    "dwd_ast_info": "资产基础信息表",
    "dwd_rsk_credit": "内部信用评级表",
    "dwd_rsk_credit_position": "信用风险持仓表",
    "dwd_rsk_sentiment": "舆情事件表",
    "dwd_cust_info": "客户主表",
    "dwd_cust_make_pstn_info": "客户建仓信息表",
    "dwd_ast_party": "资产参与方表",
    "dwd_crtd_main_rela_rela_info": "主体关联关系表",
    "dwd_crtd_agme_info": "增信措施信息表",
    "zysc_ptl_info_records": "产品信息记录表",
    "zysc_ptl_holder_records": "产品持有人记录表",
    "dwd_mkt_bond": "债券行情表",
    "dwd_val_valtable": "估值汇总表",
    "dwd_val_asset_detail": "资产估值明细",
    "dwd_trn_order": "委托订单表",
    "dwd_trn_trade_ast": "资产交易明细",
    "assets": "资产列表", "asset_prices": "资产行情",
    "dwd_ast_fiveclass": "资产五级分类表",
    "dwd_isr_institution_finance": "机构财务信息表",
    "dwd_ptl_cedetail": "产品分红明细",
    "dwd_ptl_holder_summary": "产品持有人汇总",
    "dwd_val_detail": "估值明细表",
    "dwd_val_income": "收入明细表",
    "dwd_val_expense": "费用明细表",
    "dwd_val_cash_flow": "现金流明细表",
    "dwd_val_fx_exposure": "外汇敲口表",
    "dwd_val_duration_bucket": "久期分桶表",
    "dwd_val_concentration": "集中度表",
    "dwd_ast_info_ch": "中债估值表",
    "dwd_ast_info_zg": "中证估值表",
    "dwd_ast_yield_info": "收益率信息表",
    "dwd_ast_cf_plan": "现金流计划表",
    "dwd_ast_pledge": "质押信息表",
    "dwd_ast_flow_trade": "流通交易表",
    "dwd_ast_rating": "信用评级表",
    "dwd_ast_guarantor": "担保人信息表",
    "dwd_ast_clause": "条款信息表",
    "dwd_ast_holder": "资产持有人表",
    "dwd_ast_event": "生命周期事件表",
    "dwd_ast_bond": "债券资产信息",
    "dwd_ast_fund": "基金资产信息",
    "dwd_ast_stock": "股票资产信息",
    "dwd_mkt_equity": "股票行情表",
    "dwd_mkt_fund": "基金净值行情表",
    "dwd_mkt_index": "指数行情表",
    "dwd_mkt_fx": "外汇行情表",
    "dwd_mkt_ir": "利率行情表",
    "dwd_mkt_commodity": "大宗商品行情表",
    "dwd_mkt_bond_valuation": "债券估值行情",
    "dwd_mkt_fund_nav": "基金净值行情",
    "dwd_mkt_stock_price": "股票价格行情",
    "dwd_mkt_calendar": "交易日历",
    "dwd_mkt_rating_action": "评级动作表",
    "dwd_mkt_credit_spread": "信用利差表",
    "dwd_txn_trade_record": "交易记录表",
    "dwd_txn_settlement": "结算明细表",
    "dwd_sel_channel": "销售渠道表",
    "dwd_sale_psn_info": "销售人员信息表",
    "dwd_cst_info": "客户信息表",
    "dwd_rsk_exposure": "风险敲口表",
    "dwd_rsk_limit": "风险限额表",
    "dwd_rsk_guarantee": "担保信息表",
    "dwd_rsk_event": "风险事件表",
    "subject_risk_import_batches": "风险导入批次",
    "zysc_ptl_info_import_batches": "产品信息导入批次",
    "zysc_ptl_holder_import_batches": "持有人导入批次",
}


def _get_field_zh(field: str) -> str:
    """获取字段的中文名"""
    return _FIELD_ZH_MAP.get(field, field)


def _get_table_zh(table: str) -> str:
    """获取表的中文名"""
    return _TABLE_ZH_MAP.get(table, table)


def _build_semantic_desc(left_parts: list[str], right_parts: list[str]) -> str:
    """为一条 join 条件生成人类可读的语义描述"""
    l_table = left_parts[0] if len(left_parts) == 2 else ""
    l_field = left_parts[-1]
    r_table = right_parts[0] if len(right_parts) == 2 else ""
    r_field = right_parts[-1]

    l_table_zh = _get_table_zh(l_table)
    r_table_zh = _get_table_zh(r_table)
    l_field_zh = _get_field_zh(l_field)
    r_field_zh = _get_field_zh(r_field)

    # 如果两边字段相同（常见于 PK-FK 关联）
    if l_field == r_field:
        field_desc = l_field_zh if l_field_zh != l_field else l_field
        return f"通过【{field_desc}】关联{l_table_zh}与{r_table_zh}"
    else:
        l_desc = l_field_zh if l_field_zh != l_field else l_field
        r_desc = r_field_zh if r_field_zh != r_field else r_field
        return f"通过{l_table_zh}的【{l_desc}】匹配{r_table_zh}的【{r_desc}】"


def _parse_join_conditions(join_path_str: str) -> list[dict]:
    """将 'a.f1=b.f2 | c.f3=d.f4' 解析为结构化列表"""
    if not join_path_str:
        return []
    conditions = []
    for cond in join_path_str.split("|"):
        cond = cond.strip()
        if not cond or "=" not in cond:
            continue
        parts = cond.split("=", 1)
        left = parts[0].strip()
        right = parts[1].strip()
        # 解析 table.field
        l_parts = left.rsplit(".", 1)
        r_parts = right.rsplit(".", 1)
        l_table = l_parts[0] if len(l_parts) == 2 else ""
        l_field = l_parts[-1]
        r_table = r_parts[0] if len(r_parts) == 2 else ""
        r_field = r_parts[-1]
        conditions.append({
            "left_table": l_table,
            "left_field": l_field,
            "right_table": r_table,
            "right_field": r_field,
            "left_table_zh": _get_table_zh(l_table),
            "right_table_zh": _get_table_zh(r_table),
            "left_field_zh": _get_field_zh(l_field),
            "right_field_zh": _get_field_zh(r_field),
            "semantic": _build_semantic_desc(l_parts, r_parts),
            "raw": cond,
        })
    return conditions


class LineageCollector:
    """收集对话过程中所有工具的血缘元数据"""

    def __init__(self):
        self._metas: list[dict] = []

    def collect(self, tool_result: dict | str):
        """从工具结果中提取 _lineage_meta"""
        if isinstance(tool_result, str):
            try:
                tool_result = json.loads(tool_result)
            except (json.JSONDecodeError, TypeError):
                return
        if isinstance(tool_result, dict) and "_lineage_meta" in tool_result:
            self._metas.append(tool_result["_lineage_meta"])

    def summarize(self) -> dict:
        """汇总所有血缘信息（含 contribution_level 分级 + 结构化 join_paths）"""
        all_tables: dict[str, dict] = {}
        all_domains: set[str] = set()
        all_profiles: list[str] = []
        all_join_paths: list[str] = []
        all_fields: dict[str, list[str]] = {}

        # ── 用于 contribution_level 判定的集合 ──
        router_tables: set[str] = set()   # smart_router 推荐的候选表
        queried_tables: set[str] = set()  # 实际有数据返回的表

        for meta in self._metas:
            op = meta.get("query_operation", "")
            recs = meta.get("records_returned", 0)
            tables_used = meta.get("tables_used", [])

            # 识别 smart_router 候选（仅元数据推荐，未实际查询）
            if op == "smart_table_router":
                router_tables.update(tables_used)
            # 识别实际查询（有数据返回）
            if recs > 0 and op != "smart_table_router":
                queried_tables.update(tables_used)

            # 收集表
            for table in tables_used:
                if table and table not in all_tables:
                    all_tables[table] = {
                        "name": table,
                        "domain": "",
                        "display_name": _get_table_zh(table),
                        "records_returned": 0,
                        "contribution_level": "secondary",
                    }
                if table and table in all_tables:
                    all_tables[table]["records_returned"] += recs

            # 收集域
            for domain in meta.get("domains_involved", []):
                if domain:
                    all_domains.add(domain)
                    for t in tables_used:
                        if t in all_tables:
                            all_tables[t]["domain"] = domain

            # 收集画像引用
            for profile in meta.get("profiles_referenced", []):
                if profile and profile not in all_profiles:
                    all_profiles.append(profile)

            # 收集关联路径
            join_path = meta.get("join_path", "")
            if join_path and join_path not in all_join_paths:
                all_join_paths.append(join_path)

            # 收集字段
            for table, fields in meta.get("fields_accessed", {}).items():
                if table not in all_fields:
                    all_fields[table] = []
                for f in fields:
                    if f not in all_fields[table]:
                        all_fields[table].append(f)

        # ── 计算 contribution_level ──
        primary_count = 0
        secondary_count = 0
        candidate_count = 0
        for tname, tinfo in all_tables.items():
            if tname in queried_tables:
                tinfo["contribution_level"] = "primary"
                primary_count += 1
            elif tname in router_tables and tname not in queried_tables:
                tinfo["contribution_level"] = "candidate"
                candidate_count += 1
            else:
                tinfo["contribution_level"] = "secondary"
                secondary_count += 1

        tables_list = list(all_tables.values())
        domains_list = sorted(all_domains)

        # ── 结构化 join_paths ──
        join_paths_structured: list[dict] = []
        for jp_str in all_join_paths:
            conditions = _parse_join_conditions(jp_str)
            if conditions:
                join_paths_structured.append({
                    "raw": jp_str,
                    "conditions": conditions,
                    "count": len(conditions),
                })

        # 构建 deep_link
        highlight_tables = ",".join(all_tables.keys())
        deep_link = f"/analysis/data-lineage?highlight={highlight_tables}" if highlight_tables else ""

        return {
            "total_tables": len(all_tables),
            "total_domains": len(all_domains),
            "tables": tables_list,
            "domains": domains_list,
            "profiles_used": all_profiles,
            "join_paths": all_join_paths,
            "join_paths_structured": join_paths_structured,
            "fields_summary": all_fields,
            "deep_link": deep_link,
            "primary_count": primary_count,
            "secondary_count": secondary_count,
            "candidate_count": candidate_count,
        }

    @property
    def has_data(self) -> bool:
        return len(self._metas) > 0


class ChatService:
    """对话服务：管理会话并编排 Agent 执行"""

    def __init__(self):
        self._agent: InvestmentAgent | None = None
        self._context_engine: ContextEngine | None = None
        self.store = ConversationStore()
        self.memory_manager = _memory_manager
        self.tool_result_tracker = ToolResultTracker()

        # Skills 框架初始化（保护性加载，失败不影响核心对话功能）
        try:
            skills_dir = str(_PROJECT_ROOT / "app" / "agent" / "skills" / "docs")
            self._skill_loader = SkillLoader(skills_dir)
            self._skill_loader.load_all()
            self._skill_selector = SkillSelector(self._skill_loader)
        except Exception as e:
            logger.error("Skills 加载失败，技能匹配功能不可用: {}", e)
            self._skill_loader = None
            self._skill_selector = None

    @property
    def agent(self) -> InvestmentAgent:
        """懒加载 Agent 实例"""
        if self._agent is None:
            self._init_agent()
        return self._agent

    @property
    def context_engine(self) -> ContextEngine:
        """懒加载 ContextEngine 实例"""
        if self._context_engine is None:
            self._init_agent()
        return self._context_engine

    def _init_agent(self):
        """初始化 ContextEngine 和 Agent（顺序重要：Agent 依赖 ContextEngine）"""
        cfg = get_agent_settings()
        model_configs = get_model_configs()
        model_router = ModelRouter(model_configs)
        # 先创建 ContextEngine，再注入 Agent
        client, model_config = model_router.get_client()
        self._context_engine = ContextEngine(
            llm_client=client,
            max_context_tokens=model_config.max_context,
            compress_threshold=cfg.AGENT_COMPRESS_THRESHOLD,
            tool_result_max_chars=cfg.AGENT_TOOL_RESULT_MAX_CHARS,
            model_name=model_config.name,
        )
        self._agent = InvestmentAgent(
            model_router=model_router,
            tool_registry=tool_registry,
            max_tool_rounds=cfg.AGENT_MAX_TOOL_ROUNDS,
            context_engine=self._context_engine,
        )

    async def _ensure_ready(self):
        """确保索引等前置条件就绪"""
        await self.store.ensure_indexes()

    def _generate_plan_from_skill(self, skill, conversation_id: str) -> ExecutionPlan:
        """从 Skill 的 steps 生成 ExecutionPlan"""
        plan_steps = []
        for step in skill.steps:
            description = f"{step.name}: {step.description}" if step.description else step.name
            # 将 condition/skip_if 信息嵌入描述中，供 agent 在执行时判断
            if step.condition:
                description += f" [执行条件: {step.condition}]"
            if step.skip_if:
                description += f" [跳过条件: {step.skip_if}]"
            plan_steps.append(PlanStep(
                step=description,
                status=StepStatus.PENDING,
                tools=step.tools or [],
            ))

        plan = ExecutionPlan(
            goal=f"执行 {skill.display_name} 技能流程",
            steps=plan_steps,
            explanation=f"由 Skill '{skill.name}' 自动生成的执行计划",
        )
        if plan.steps:
            plan.steps[0].status = StepStatus.IN_PROGRESS
        return plan

    async def _auto_advance_plan_after_tool(
        self,
        conversation_id: str,
        tool_name: str,
        result_data,
    ):
        """在工具成功结束后按顺序自动推进一条计划步骤，并通过 SSE plan_update 展示进度。"""
        if not tool_name or tool_name == "update_plan":
            return None
        if not result_data or not isinstance(result_data, dict) or not result_data.get("success"):
            return None

        plan = await _plan_manager.get_plan(conversation_id)
        if not plan or not plan.steps:
            return None

        # 匹配第一个仍未完成且 tools 中包含本工具名的步骤（允许跳过前提条件类步骤）
        idx: int | None = None
        for i, s in enumerate(plan.steps):
            if s.status == StepStatus.COMPLETED:
                continue
            tools = s.tools or []
            if tool_name not in tools:
                continue
            idx = i
            break

        if idx is None:
            return None

        # 若直接完成了较后步骤，将中间仍为待处理的步骤标为已跳过，避免进度条长期停在 0/N
        skip_label = "(已跳过)"
        for j in range(idx):
            if plan.steps[j].status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                plan.steps[j].status = StepStatus.COMPLETED
                plan.steps[j].result_summary = skip_label

        preview = ""
        msg = result_data.get("message")
        if msg:
            preview = str(msg).strip().replace("\n", " ")[:100]

        plan.steps[idx].status = StepStatus.COMPLETED
        if preview:
            plan.steps[idx].result_summary = preview

        if idx + 1 < len(plan.steps) and plan.steps[idx + 1].status == StepStatus.PENDING:
            plan.steps[idx + 1].status = StepStatus.IN_PROGRESS

        save_result = await _plan_manager.save_plan(conversation_id, plan)
        if not save_result.get("success"):
            logger.warning("[ChatService] 自动推进计划保存失败: {}", save_result.get("error"))
            return None

        return {
            "goal": plan.goal,
            "steps": [s.to_dict() for s in plan.steps],
            "source": "tool_auto",
        }

    def _rebuild_messages(self, history: list[dict]) -> list[dict]:
        """重建可回放的消息链，正确处理 tool_calls 和 tool result。

        包含防守性逻辑：检测历史消息中重复的 tool_call_id 并重映射为唯一 ID，
        避免 DeepSeek 等 API 因 Duplicate tool_call_id 返回 400 错误。
        """
        messages: list[dict] = []
        valid_tool_call_ids: set[str] = set()

        # ---- 第 0 步：检测重复 tool_call_id 并生成重映射表 ----
        id_remap: dict[tuple[int, int], str] = {}  # (assistant_round, tc_idx) -> new_id
        seen_ids: set[str] = set()
        assistant_round: int = 0
        has_duplicates: bool = False

        for msg in history:
            if msg["role"] == "assistant" and msg.get("tool_calls_raw"):
                for tc_idx, tc in enumerate(msg["tool_calls_raw"]):
                    if isinstance(tc, dict) and tc.get("id"):
                        old_id = tc["id"]
                        if old_id in seen_ids:
                            new_id = f"soft_tool_{uuid.uuid4().hex[:8]}"
                            id_remap[(assistant_round, tc_idx)] = new_id
                            has_duplicates = True
                        else:
                            seen_ids.add(old_id)
                        valid_tool_call_ids.add(old_id)
                assistant_round += 1

        if has_duplicates:
            logger.info(
                "rebuild_messages_dedup",
                extra={"remapped_count": len(id_remap)},
            )

        # ---- 第 1 步：重建消息，应用重映射 ----
        assistant_round = 0
        current_remap: dict[str, str] = {}  # 当前轮次 old_id -> new_id

        for msg in history:
            if msg["role"] == "assistant" and msg.get("tool_calls_raw"):
                current_remap = {}
                updated_tool_calls: list[dict] = []
                for tc_idx, tc in enumerate(msg["tool_calls_raw"]):
                    if isinstance(tc, dict):
                        old_id = tc.get("id", "")
                        new_id = id_remap.get((assistant_round, tc_idx), old_id)
                        if new_id != old_id:
                            current_remap[old_id] = new_id
                        updated_tool_calls.append({**tc, "id": new_id})
                    else:
                        updated_tool_calls.append(tc)
                messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": updated_tool_calls,
                })
                assistant_round += 1
            elif msg["role"] == "tool" and msg.get("tool_call_id"):
                if msg["tool_call_id"] in valid_tool_call_ids:
                    remapped_id = current_remap.get(
                        msg["tool_call_id"], msg["tool_call_id"]
                    )
                    # 对已压缩的 tool 消息，直接使用存储的摘要内容（不加载完整版）
                    tool_content = msg.get("content", "")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": remapped_id,
                        "content": tool_content,
                    })
                # 孤立的 tool result 直接跳过
            else:
                # user / assistant(无 tool_calls) 消息
                messages.append({
                    "role": msg["role"],
                    "content": msg.get("content") or "",
                })

        # ---- 第 2 步：确保每个 assistant 的 tool_calls 都有对应的 tool result ----
        final_messages: list[dict] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            final_messages.append(msg)
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                expected_ids = {
                    tc["id"] for tc in msg["tool_calls"]
                    if isinstance(tc, dict) and tc.get("id")
                }
                found_ids: set[str] = set()
                j = i + 1
                while j < len(messages) and messages[j]["role"] == "tool":
                    if messages[j].get("tool_call_id") in expected_ids:
                        found_ids.add(messages[j]["tool_call_id"])
                    final_messages.append(messages[j])
                    j += 1
                # 合成缺失的 tool result 防止 OpenAI API 报错
                for missing_id in expected_ids - found_ids:
                    final_messages.append({
                        "role": "tool",
                        "tool_call_id": missing_id,
                        "content": "[系统提示] 此工具的执行结果在历史记录中丢失，请忽略此工具调用的结果，基于其他可用信息继续分析。",
                    })
                i = j
            else:
                i += 1
        return final_messages

    async def _check_conversation_length_warning(self, conversation_id: str) -> str | None:
        """检查对话消息条数，超过阈值时返回告警"""
        count = await self.store.count_messages(conversation_id)
        if count > 80:
            return (
                f"当前对话已有 {count} 条消息，建议新建对话以保持最佳响应质量。"
                "长对话可能导致上下文压缩频繁，影响分析准确性。"
            )
        return None

    # ------------------------------------------------------------------
    # 附件上下文构建
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_import_type(columns: list) -> str | None:
        """根据列名自动检测可能的 import_type。"""
        col_upper = {str(c).strip().upper() for c in columns}
        col_stripped = {str(c).strip() for c in columns}
        # 交易日历检测（优先于其他类型，因为 trade_dates 列名特征明确）
        trade_date_cols = {"TRADE_DATES", "TRADE_DATE", "交易日", "交易日期"}
        if col_upper & trade_date_cols:
            return "trade_dates"
        fx_currencies = {"EUR", "USD", "HKD", "CNH"}
        if len(col_upper & fx_currencies) >= 1:
            return "fx"
        price_cols = {"CLOSE", "收盘价", "收盘", "收盘价*"}
        if col_upper & price_cols:
            return "price"
        info_cols = {"CODE", "代码", "资产代码", "资产代码*"}
        if col_upper & info_cols:
            return "asset_info"
        # 宽表行情检测：列名为已知资产名称或资产代码时，识别为 price 类型
        from app.monitor.config import ASSET_NAME_TO_CODE, ASSET_CODE_TO_NAME
        known_names = set(ASSET_NAME_TO_CODE.keys())
        known_codes = set(ASSET_CODE_TO_NAME.keys())
        matched = col_stripped & (known_names | known_codes)
        if len(matched) >= 2:
            return "price"
        return None

    @staticmethod
    def _build_attachment_context(attachments: list[str] | None) -> str | None:
        """根据 attachment_id 列表构建附件上下文描述，供 LLM 感知用户上传的文件。

        对 Excel/CSV 文件会读取完整数据并计算每列的精确统计（首末日期、非空数量、首末值），
        避免 LLM 仅依赖前几行预览信息推断而出现"待确认（前5行全为null）"的错误回复。

        Returns:
            附件上下文字符串，无附件或全部失效时返回 None
        """
        import pandas as pd
        import numpy as np

        if not attachments:
            return None

        descriptions = []
        expired_ids = []
        action_hints = []
        for att_id in attachments:
            meta = AttachmentService.get_attachment(att_id)
            if not meta:
                expired_ids.append(att_id)
                continue
            columns = meta.get("preview", {}).get("columns", [])
            import_type = ChatService._detect_import_type(columns)

            # 尝试读取完整文件以计算精确的列统计
            file_path = AttachmentService.get_file_path(att_id)
            col_stats_text = None
            if file_path and meta.get('format') in ('xlsx', 'xls', 'csv'):
                try:
                    if meta['format'] == 'csv':
                        for enc in ('utf-8', 'gbk', 'gb2312'):
                            try:
                                df = pd.read_csv(str(file_path), index_col=0, parse_dates=True, encoding=enc)
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            df = pd.read_csv(str(file_path), index_col=0, parse_dates=True, encoding='utf-8', errors='replace')
                    else:
                        df = pd.read_excel(str(file_path), index_col=0, parse_dates=True)

                    # 文件过大时只计算统计，不展示逐行数据
                    total_rows = len(df)
                    total_cols = len(df.columns)

                    stats_lines = []
                    stats_lines.append(f"文件: {meta['file_name']} ({total_rows}行 × {total_cols}列)")

                    # 索引日期范围
                    if hasattr(df.index, 'min') and total_rows > 0:
                        idx_min = df.index.min()
                        idx_max = df.index.max()
                        idx_min_str = idx_min.strftime('%Y-%m-%d') if hasattr(idx_min, 'strftime') else str(idx_min)
                        idx_max_str = idx_max.strftime('%Y-%m-%d') if hasattr(idx_max, 'strftime') else str(idx_max)
                        stats_lines.append(f"索引(日期)范围: {idx_min_str} ~ {idx_max_str}")

                    stats_lines.append("各列精确统计:")

                    # 限制展示列数量（超过30列时只显示前30列并提示）
                    display_cols = df.columns[:30]
                    for col in display_cols:
                        series = df[col].dropna()
                        if len(series) > 0:
                            first_date = series.index.min()
                            last_date = series.index.max()
                            first_date_str = first_date.strftime('%Y-%m-%d') if hasattr(first_date, 'strftime') else str(first_date)
                            last_date_str = last_date.strftime('%Y-%m-%d') if hasattr(last_date, 'strftime') else str(last_date)
                            # 安全格式化数值
                            try:
                                first_val = f"{float(series.iloc[0]):.4f}"
                            except (ValueError, TypeError):
                                first_val = str(series.iloc[0])
                            try:
                                last_val = f"{float(series.iloc[-1]):.4f}"
                            except (ValueError, TypeError):
                                last_val = str(series.iloc[-1])
                            stats_lines.append(
                                f"  - {col}: {len(series)}条有效数据, "
                                f"日期 {first_date_str} ~ {last_date_str}, "
                                f"首值={first_val}, 末值={last_val}"
                            )
                        else:
                            stats_lines.append(f"  - {col}: 全空列(0条有效数据)")

                    if len(df.columns) > 30:
                        stats_lines.append(f"  ... 还有 {len(df.columns) - 30} 列未展示")

                    col_stats_text = "\n".join(stats_lines)
                except Exception as e:
                    logger.warning("读取文件计算完整列统计失败: {}, 退回简单预览", e)
                    col_stats_text = None

            # 构建描述文本
            if col_stats_text:
                desc = (
                    f"- attachment_id={att_id}\n"
                    f"  {col_stats_text}"
                )
            else:
                # 退回到原来的简单预览
                row_count = meta.get("preview", {}).get("total_rows", "未知")
                desc = (
                    f"- attachment_id={att_id}, "
                    f"文件名={meta['file_name']}, "
                    f"格式={meta['format']}, "
                    f"大小={meta['file_size']}字节, "
                    f"列名={columns}, "
                    f"行数={row_count}"
                )
            if import_type:
                desc += f"\n  自动检测import_type={import_type}"
            descriptions.append(desc)

            # 生成执行步骤提示
            if import_type:
                action_hints.append(
                    f"附件 {att_id} (import_type={import_type})：\n"
                    f"  1. data_import(action='validate', attachment_id='{att_id}', import_type='{import_type}') —— 校验文件格式\n"
                    f"  2. data_import(action='preview', attachment_id='{att_id}', import_type='{import_type}') —— 预览数据并对比数据库现有数据，向用户展示对比结果并询问是否确认导入\n"
                    f"  3. 用户确认后才执行: data_import(action='import', attachment_id='{att_id}', import_type='{import_type}', mode='incremental')\n"
                    f"     → import 时默认使用 mode='incremental'（仅导入新增数据），除非用户明确要求全量替换\n"
                    f"     → 增量模式只导入数据库中尚不存在的日期数据，即使文件很大也能快速完成"
                )
            else:
                # import_type 未检测到时，提供默认指引（宽表行情文件等）
                action_hints.append(
                    f"附件 {att_id} (未自动检测到类型，请根据文件内容判断)：\n"
                    f"  可能的 import_type: price(行情宽表/窄表), fx(汇率), asset_info(资产信息), trade_dates(交易日历)\n"
                    f"  如果文件第一列为日期、其余列为资产价格，应使用 import_type='price'\n"
                    f"  1. data_import(action='validate', attachment_id='{att_id}', import_type='price') —— 校验\n"
                    f"  2. data_import(action='preview', attachment_id='{att_id}', import_type='price') —— 预览\n"
                    f"  3. 用户确认后: data_import(action='import', attachment_id='{att_id}', import_type='price', mode='incremental')"
                )

        if expired_ids:
            logger.warning("附件已过期或不存在: {}", expired_ids)

        if not descriptions:
            return None

        attachment_context = "\n".join(descriptions)
        action_text = "\n".join(action_hints) if action_hints else ""

        return (
            "\n\n--- 用户上传的附件 ---\n"
            f"{attachment_context}\n\n"
            "【重要指令】你必须直接使用 data_import 工具执行完整的数据导入流程，"
            "不要回复\"\u4e0d\u652f\u6301\"或\"\u65e0\u6cd5\u4e0a\u4f20\"，data_import 工具的 import 操作已完整实现，"
            "可以将 Excel/CSV 文件数据写入 MongoDB 数据库。\n\n"
            "【数据已精确解析】上方列统计信息是从完整文件计算得到的精确结果，"
            "你可以直接引用这些统计数据回复用户，无需说\"待确认\"或\"前N行为null\"。\n\n"
            "请按以下步骤依次调用 data_import 工具：\n"
            f"{action_text}\n\n"
            "注意事项：\n"
            "- 列名 'Unnamed: 0' 通常是日期列，validate 和 import 内部会自动使用第一列作为日期索引\n"
            "- validate 校验通过后请继续执行 preview\n"
            "- preview 会返回文件数据与数据库现有数据的对比结果（新增数量、覆盖数量、日期范围）\n"
            "- 你必须在 preview 后向用户展示对比结果，并明确询问用户是否确认执行导入\n"
            "- 只有用户明确确认后，才能执行 import 操作\n"
            "- 【重要】import 时默认使用 mode='incremental'（增量模式，仅导入新增数据），除非用户明确要求全量替换\n"
            "- 增量模式只导入数据库中尚不存在的日期数据，即使文件很大也能快速完成\n"
            "- 所有导入操作都通过 data_import 工具完成，不需要用户手动操作\n"
            "--- 附件信息结束 ---"
        )

    # ------------------------------------------------------------------
    # 场景化辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    def _append_turn_addon(system_prompt: str, system_turn_addon: str | None) -> str:
        """将客户端传入的单轮补充说明拼到系统提示末尾（不写入用户消息历史）。"""
        if not system_turn_addon:
            return system_prompt
        addon = system_turn_addon.strip()
        if not addon:
            return system_prompt
        return system_prompt + "\n\n## 本轮任务补充指令（仅此一轮）\n" + addon

    def _resolve_active_toolsets(self, scene: str | None) -> list[str] | None:
        """根据场景解析活跃工具集名称列表。

        Args:
            scene: 业务场景标识，None 时返回 AUTO_MODE_TOOLS

        Returns:
            工具集名称列表，用于 ToolRegistry.get_filtered_openai_tools() 过滤
        """
        if scene is None:
            # 智能匹配模式：使用 AUTO_MODE_TOOLS，由 Agent 自动扩展
            return list(ToolRegistry.AUTO_MODE_TOOLS)
        scene_tools = ToolRegistry.SCENE_TOOLSETS.get(scene)
        if scene_tools:
            # 场景工具 + 通用工具（COMMON_TOOLS 已在 get_filtered_openai_tools 中自动加入）
            return [scene]
        # 未知场景：退回全量工具
        logger.warning("scene_toolset_unknown", extra={"scene": scene})
        return None

    def _prioritize_skills_by_scene(
        self,
        skills: list,
        scene: str | None,
    ) -> list:
        """将 Skill 列表按场景相关性排序：与当前场景 toolset 匹配的 Skill 优先。

        Args:
            skills: SkillSelector.match() 返回的 Skill 列表
            scene: 当前业务场景标识

        Returns:
            重排序后的 Skill 列表
        """
        if not skills or scene is None:
            return skills
        scene_toolset = set(ToolRegistry.SCENE_TOOLSETS.get(scene, []))
        if not scene_toolset:
            return skills

        matched: list = []
        others: list = []
        for skill in skills:
            skill_toolset = skill.toolset or ""
            if isinstance(skill_toolset, str):
                skill_tool_names = set(t.strip() for t in skill_toolset.split(",") if t.strip())
            else:
                skill_tool_names = set(skill_toolset)
            if skill_tool_names & scene_toolset:
                matched.append(skill)
            else:
                others.append(skill)
        return matched + others

    # ------------------------------------------------------------------
    # 非流式
    # ------------------------------------------------------------------
    async def process_message(
        self,
        conversation_id: str | None,
        message: str,
        user_id: str = "default",
        scene: str | None = None,
        system_turn_addon: str | None = None,
        attachments: list[str] | None = None,
    ) -> AgentReply:
        """处理用户消息并返回 Agent 回复

        Args:
            conversation_id: 对话 ID，None 时创建新对话
            message: 用户消息
            user_id: 用户标识
            scene: 业务场景标识，None 时智能匹配（使用 AUTO_MODE_TOOLS）
            system_turn_addon: 仅当轮附加系统指令，不入库
            attachments: 用户上传的附件ID列表
        """
        try:
            # 1. 确保索引就绪
            await self._ensure_ready()

            # 2. 如果没有 conversation_id，创建新对话
            if not conversation_id:
                title = message[:30] if len(message) > 30 else message
                conversation_id = await self.store.create_conversation(user_id, title=title)

            # 2. 保存用户消息
            await self.store.add_message(conversation_id, role="user", content=message)

            # 3. 加载历史消息
            cfg = get_agent_settings()
            history = await self.store.get_messages(
                conversation_id, limit=cfg.AGENT_CONVERSATION_MAX_HISTORY
            )

            # 4. 构建 messages：通过 ContextEngine 智能组装（含压缩）
            rebuilt = self._rebuild_messages(history)

            # 4.1 场景化 System Prompt + 记忆集成
            self.memory_manager.reset_turn_counter(conversation_id)
            memory_context = await self.memory_manager.get_relevant_context(user_id, message)
            system_prompt = get_system_prompt(scene)
            logger.info("scene_prompt_selected", extra={"scene": scene})
            if memory_context:
                system_prompt = system_prompt + "\n\n" + memory_context

            # 4.1c 对话长度告警
            length_warning = await self._check_conversation_length_warning(conversation_id)
            if length_warning:
                system_prompt += f"\n\n[系统告警] {length_warning}"

            # 4.1b 注入 DataContext 数据摘要
            ctx = DataContext.get_instance(conversation_id)
            context_summary = ctx.get_context_summary()
            if context_summary:
                system_prompt += f"\n\n{context_summary}"

            # 4.2 场景化工具集 + Skill 工作流注入
            active_toolsets = self._resolve_active_toolsets(scene)
            if self._skill_selector:
                matched_skills = self._skill_selector.match(message)
                # 场景优先：优先保留与当前场景 toolset 匹配的 Skill
                matched_skills = self._prioritize_skills_by_scene(matched_skills, scene)
                if matched_skills:
                    skill_guidance = "\n\n".join([s.to_prompt_section() for s in matched_skills])
                    system_prompt += f"\n\n[工作流指导]\n{skill_guidance}"
                    # 收集首个匹配 Skill 的 toolset 信息，补充到 active_toolsets
                    first_skill = matched_skills[0]
                    if first_skill.toolset:
                        skill_toolsets = (
                            [t.strip() for t in first_skill.toolset.split(",")]
                            if isinstance(first_skill.toolset, str)
                            else first_skill.toolset
                        )
                        # 场景已指定时合并，场景为 None 时用 Skill 的 toolset
                        if active_toolsets:
                            active_toolsets = list(set(active_toolsets) | set(skill_toolsets))
                        else:
                            active_toolsets = skill_toolsets
                    # 对首个匹配 Skill，若有 steps 且 show_plan=True 且当前对话无活跃计划，自动生成执行计划
                    # show_plan 默认 False，仅复杂多步骤 Skill 显式开启时才展示进度面板
                    if first_skill.steps and first_skill.show_plan:
                        existing_plan = await _plan_manager.get_plan(conversation_id)
                        if not existing_plan:
                            plan = self._generate_plan_from_skill(first_skill, conversation_id)
                            save_result = await _plan_manager.save_plan(conversation_id, plan)
                            if save_result.get("success"):
                                logger.info("[ChatService] 从 Skill '{}' 自动生成执行计划", first_skill.name)
                            else:
                                logger.warning("[ChatService] 自动计划保存失败: {}", save_result.get("error"))

            # 4.3 注入当前计划状态
            current_plan = await _plan_manager.get_plan(conversation_id)
            if current_plan:
                plan_text = _plan_manager.format_plan_for_prompt(current_plan)
                system_prompt += f"\n\n{plan_text}"

            system_prompt = self._append_turn_addon(system_prompt, system_turn_addon)

            # 4.4 注入附件上下文到最后一条 user 消息
            attachment_ctx = self._build_attachment_context(attachments)
            if attachment_ctx:
                logger.info("注入附件上下文, attachments={}", attachments)
                # 找到 rebuilt 中最后一条 user 消息并追加附件信息
                for i in range(len(rebuilt) - 1, -1, -1):
                    if rebuilt[i]["role"] == "user":
                        rebuilt[i] = {
                            **rebuilt[i],
                            "content": rebuilt[i].get("content", "") + attachment_ctx,
                        }
                        break

            messages = await self.context_engine.prepare_messages(
                system_prompt=system_prompt,
                history=rebuilt,
            )

            # 5. 调用 Agent（传入 tool_context 便于记忆工具获取 user_id/conversation_id，active_toolsets 用于动态工具过滤）
            tool_context = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "_tool_result_tracker": self.tool_result_tracker,
            }
            result = await self.agent.run(messages, tool_context=tool_context, active_toolsets=active_toolsets)

            # 6. 保存 assistant 回复
            await self.store.add_message(
                conversation_id,
                role="assistant",
                content=result["content"],
                tool_calls=result["tool_calls"] if result["tool_calls"] else None,
                tool_calls_raw=result.get("tool_calls_raw"),
            )

            # 7. 返回 AgentReply
            return AgentReply(
                conversation_id=conversation_id,
                content=result["content"],
                tool_calls=result["tool_calls"],
            )
        except Exception as e:
            logger.error("process_message 异常: {}", ErrorHandler.sanitize_error_message(str(e)))
            # 错误已经过 ErrorHandler 处理，到这里说明是不可重试的
            handler = ErrorHandler()
            category = handler.classify(e)
            safe_msg = handler.sanitize_error_message(str(e))
            logger.error("[ChatService] Agent 执行失败 ({}): {}", category.value, safe_msg)
            return AgentReply(
                conversation_id=conversation_id or "",
                content=f"抱歉，处理您的请求时遇到问题：{safe_msg}",
                tool_calls=[],
            )

    # ------------------------------------------------------------------
    # 流式
    # ------------------------------------------------------------------
    async def process_message_stream(
        self,
        conversation_id: str | None,
        message: str,
        user_id: str = "default",
        scene: str | None = None,
        system_turn_addon: str | None = None,
        attachments: list[str] | None = None,
    ):
        """流式处理用户消息，yield SSE 格式字符串。

        Args:
            conversation_id: 对话 ID，None 时创建新对话
            message: 用户消息
            user_id: 用户标识
            scene: 业务场景标识，None 时智能匹配（使用 AUTO_MODE_TOOLS）
            system_turn_addon: 仅当轮附加系统指令，不入库
            attachments: 用户上传的附件ID列表

        Yields:
            str: "event: {event_type}\\ndata: {json}\\n\\n"
        """
        try:
            # 1. 确保索引就绪
            try:
                await asyncio.wait_for(self._ensure_ready(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("[ChatService stream] 索引准备超时")
                yield _sse("error", {"error": "系统初始化超时，请重试"})
                return
            except Exception as e:
                logger.error("[ChatService stream] 索引准备失败: {}", e)
                yield _sse("error", {"error": f"系统初始化失败: {str(e)[:100]}"})
                return

            # 2. 创建或复用对话
            if not conversation_id:
                title = message[:30] if len(message) > 30 else message
                try:
                    conversation_id = await asyncio.wait_for(
                        self.store.create_conversation(user_id, title=title),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    logger.error("[ChatService stream] 创建对话超时")
                    yield _sse("error", {"error": "对话创建超时，请重试"})
                    return
                except Exception as e:
                    logger.error("[ChatService stream] 创建对话失败: {}", e)
                    yield _sse("error", {"error": f"对话创建失败: {str(e)[:100]}"})
                    return

            # yield conversation_id 事件
            yield _sse("conversation_id", {"conversation_id": conversation_id})

            # 2. 保存用户消息
            await self.store.add_message(conversation_id, role="user", content=message)

            # 3. 加载历史
            cfg = get_agent_settings()
            history = await self.store.get_messages(
                conversation_id, limit=cfg.AGENT_CONVERSATION_MAX_HISTORY
            )

            # 4. 构建 messages：通过 ContextEngine 智能组装（含压缩）
            rebuilt = self._rebuild_messages(history)

            # 4.1 场景化 System Prompt + 记忆集成
            self.memory_manager.reset_turn_counter(conversation_id)
            memory_context = await self.memory_manager.get_relevant_context(user_id, message)
            system_prompt = get_system_prompt(scene)
            logger.info("scene_prompt_selected_stream", extra={"scene": scene})
            if memory_context:
                system_prompt = system_prompt + "\n\n" + memory_context

            # 4.1c 对话长度告警
            length_warning = await self._check_conversation_length_warning(conversation_id)
            if length_warning:
                system_prompt += f"\n\n[系统告警] {length_warning}"

            # 4.1b 注入 DataContext 数据摘要
            ctx = DataContext.get_instance(conversation_id)
            context_summary = ctx.get_context_summary()
            if context_summary:
                system_prompt += f"\n\n{context_summary}"

            # 4.2 场景化工具集 + Skill 工作流注入
            active_toolsets = self._resolve_active_toolsets(scene)
            if self._skill_selector:
                matched_skills = self._skill_selector.match(message)
                # 场景优先：优先保留与当前场景 toolset 匹配的 Skill
                matched_skills = self._prioritize_skills_by_scene(matched_skills, scene)
                if matched_skills:
                    skill_guidance = "\n\n".join([s.to_prompt_section() for s in matched_skills])
                    system_prompt += f"\n\n[工作流指导]\n{skill_guidance}"
                    # 收集首个匹配 Skill 的 toolset 信息，补充到 active_toolsets
                    first_skill = matched_skills[0]
                    if first_skill.toolset:
                        skill_toolsets = (
                            [t.strip() for t in first_skill.toolset.split(",")]
                            if isinstance(first_skill.toolset, str)
                            else first_skill.toolset
                        )
                        if active_toolsets:
                            active_toolsets = list(set(active_toolsets) | set(skill_toolsets))
                        else:
                            active_toolsets = skill_toolsets
                    # 对首个匹配 Skill，若有 steps 且 show_plan=True 且当前对话无活跃计划，自动生成执行计划
                    if first_skill.steps and first_skill.show_plan:
                        existing_plan = await _plan_manager.get_plan(conversation_id)
                        if not existing_plan:
                            plan = self._generate_plan_from_skill(first_skill, conversation_id)
                            save_result = await _plan_manager.save_plan(conversation_id, plan)
                            if save_result.get("success"):
                                logger.info("[ChatService] 从 Skill '{}' 自动生成执行计划（流式）", first_skill.name)
                                plan_data = {
                                    "goal": plan.goal,
                                    "steps": [s.to_dict() for s in plan.steps],
                                    "source": "skill_auto",
                                }
                                yield _sse("plan_update", plan_data)
                            else:
                                logger.warning("[ChatService] 自动计划保存失败: {}", save_result.get("error"))

            # 4.3 注入当前计划状态
            current_plan = await _plan_manager.get_plan(conversation_id)
            if current_plan:
                plan_text = _plan_manager.format_plan_for_prompt(current_plan)
                system_prompt += f"\n\n{plan_text}"

            system_prompt = self._append_turn_addon(system_prompt, system_turn_addon)

            # 4.4 注入附件上下文到最后一条 user 消息
            attachment_ctx = self._build_attachment_context(attachments)
            if attachment_ctx:
                logger.info("注入附件上下文(流式), attachments={}", attachments)
                for i in range(len(rebuilt) - 1, -1, -1):
                    if rebuilt[i]["role"] == "user":
                        rebuilt[i] = {
                            **rebuilt[i],
                            "content": rebuilt[i].get("content", "") + attachment_ctx,
                        }
                        break

            messages = await self.context_engine.prepare_messages(
                system_prompt=system_prompt,
                history=rebuilt,
            )

            full_content = ""
            all_tool_calls: list[dict] = []
            all_tool_calls_raw: list[dict] | None = None
            lineage_collector = LineageCollector()

            # 5. 调用 Agent（ReAct 循环，传入 tool_context 和 active_toolsets）
            tool_context = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "_tool_result_tracker": self.tool_result_tracker,
            }
            async for event in self.agent.run_stream(messages, tool_context=tool_context, active_toolsets=active_toolsets):
                event_type = event["event"]
                event_data = event["data"]

                if event_type == "text_delta":
                    full_content += event_data["content"]
                elif event_type == "text_replace":
                    # 中间轮次的脑洞文字/DSML/裸 JSON 被 Agent 标记为非用户可见，
                    # 直接重置 full_content，防止持久化到最终 assistant message。
                    full_content = event_data.get("content", "") or ""
                if event_type == "tool_result":
                    all_tool_calls.append(event_data)
                    # 将工具结果存入 DataContext
                    result_data = event_data.get("result")
                    tool_name = event_data.get("name", "")
                    # 增量收集报告所需数据
                    if result_data:
                        self.tool_result_tracker.track(tool_name, result_data)
                        # 收集血缘元数据
                        lineage_collector.collect(result_data)
                    if result_data and isinstance(result_data, dict) and result_data.get("success"):
                        data = result_data.get("data", {})
                        records = data.get("records") if isinstance(data, dict) else None
                        if records and isinstance(records, list):
                            step_key = ctx.store(
                                data=records,
                                tool_name=tool_name,
                                params=event_data.get("arguments", {}),
                            )
                            result_data["step_key"] = step_key
                    # 计划 SSE：显式 update_plan，或按计划顺序在工具成功后自动推进
                    if event_data.get("name") == "update_plan":
                        updated_plan = await _plan_manager.get_plan(conversation_id)
                        if updated_plan:
                            plan_data = {
                                "goal": updated_plan.goal,
                                "steps": [
                                    {
                                        "step": s.step,
                                        "status": s.status.value,
                                        "result_summary": s.result_summary,
                                    }
                                    for s in updated_plan.steps
                                ],
                            }
                            yield _sse("plan_update", plan_data)
                    else:
                        auto_plan = await self._auto_advance_plan_after_tool(
                            conversation_id, tool_name, result_data
                        )
                        if auto_plan:
                            yield _sse("plan_update", auto_plan)
                if event_type == "message_end":
                    all_tool_calls_raw = event_data.get("tool_calls_raw")

                yield _sse(event_type, event_data)

            # 6. yield lineage_summary 事件（在所有 text_chunk 之后、保存之前）
            lineage_summary = None
            if lineage_collector.has_data:
                lineage_summary = lineage_collector.summarize()
                yield _sse("lineage_summary", lineage_summary)

            # 7. 保存 assistant 回复
            await self.store.add_message(
                conversation_id,
                role="assistant",
                content=full_content,
                tool_calls=all_tool_calls if all_tool_calls else None,
                tool_calls_raw=all_tool_calls_raw,
                lineage_summary=lineage_summary,
            )

        except Exception as e:
            logger.error("process_message_stream 异常: {}", ErrorHandler.sanitize_error_message(str(e)))
            handler = ErrorHandler()
            category = handler.classify(e)
            safe_msg = handler.sanitize_error_message(str(e))
            logger.error("[ChatService] 流式处理失败 ({}): {}", category.value, safe_msg)
            yield _sse("error", {"error": safe_msg, "category": category.value})


def _json_default(obj):
    """JSON 序列化兜底：处理 numpy、datetime 等非标准类型"""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return str(obj)


def _sse(event: str, data: dict) -> str:
    """构造 SSE 事件字符串"""
    try:
        json_str = json.dumps(data, ensure_ascii=False, default=_json_default)
        return f"event: {event}\ndata: {json_str}\n\n"
    except Exception as e:
        logger.error(f"[SSE] JSON 序列化失败: {e}, event={event}")
        return f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

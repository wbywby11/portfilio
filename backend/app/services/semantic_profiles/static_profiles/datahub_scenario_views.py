"""
DataHub 典型分析场景视图定义

5个可直接用于智能问答的分析场景，基于 L1-L5 画像构建。
每个场景包含 MongoDB aggregation 查询模板和预期输出结构。
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class ScenarioView(BaseModel):
    """分析场景视图模型"""
    scenario_id: str = Field(..., description="场景标识")
    scenario_name: str = Field(..., description="场景名称")
    description: str = Field(..., description="场景描述")
    tables_involved: List[str] = Field(default_factory=list, description="涉及表")
    analysis_dimensions: List[str] = Field(default_factory=list, description="分析维度")
    query_template: dict = Field(default_factory=dict, description="MongoDB aggregation pipeline")
    expected_output_schema: dict = Field(default_factory=dict, description="输出字段说明")
    analysis_narrative: str = Field("", description="分析叙述模板")
    related_profiles: List[str] = Field(default_factory=list, description="关联画像ID")


# ============================================================
# S1: 高风险主体全景扫描
# ============================================================
S1_HIGH_RISK_SUBJECT_SCAN = ScenarioView(
    scenario_id="datahub_s1_high_risk_scan",
    scenario_name="高风险主体全景扫描",
    description=(
        "基于 subject_risk_records 对风险信号等级为'高'的主体进行多维度扫描，"
        "按行业、省份、企业性质交叉分析，识别高风险聚集区域和系统性风险信号。"
    ),
    tables_involved=["subject_risk_records"],
    analysis_dimensions=[
        "风险等级分布", "行业分布", "省份分布", "企业性质分布",
        "规则大类分布", "高风险主体清单",
    ],
    query_template={
        "collection": "subject_risk_records",
        "pipelines": {
            "risk_level_distribution": [
                {"$group": {"_id": "$risk_signal_level", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ],
            "high_risk_by_industry": [
                {"$match": {"risk_signal_level": "高"}},
                {"$group": {
                    "_id": "$industry_classification_gb",
                    "subjects": {"$addToSet": "$subject_name"},
                    "count": {"$sum": 1},
                }},
                {"$sort": {"count": -1}},
            ],
            "high_risk_by_province": [
                {"$match": {"risk_signal_level": "高"}},
                {"$group": {
                    "_id": "$affiliated_province",
                    "subjects": {"$addToSet": "$subject_name"},
                    "count": {"$sum": 1},
                }},
                {"$sort": {"count": -1}},
            ],
            "high_risk_subject_list": [
                {"$match": {"risk_signal_level": "高"}},
                {"$group": {
                    "_id": "$subject_name",
                    "risk_count": {"$sum": 1},
                    "rule_categories": {"$addToSet": "$rule_large"},
                    "latest_date": {"$max": "$biz_date"},
                    "enterprise_nature": {"$first": "$enterprise_nature"},
                    "industry": {"$first": "$industry_classification_gb"},
                }},
                {"$sort": {"risk_count": -1}},
            ],
        },
    },
    expected_output_schema={
        "risk_level_distribution": "风险等级→数量分布",
        "high_risk_by_industry": "高风险按行业→主体清单+计数",
        "high_risk_by_province": "高风险按省份→主体清单+计数",
        "high_risk_subject_list": "高风险主体→风险次数+规则类别+最新日期",
    },
    analysis_narrative=(
        "当前共有{total_risk}条风险信号，其中高风险{high_count}条（{high_pct}%），"
        "涉及{high_subject_count}个独立主体。高风险主要集中于{top_industry}行业，"
        "{top_province}地区，以{top_nature}企业为主。"
        "重点关注：{top_subject}近期内连续触发{top_count}条高风险信号。"
    ),
    related_profiles=["l2_data_hub", "datahub_risk_subject", "datahub_risk_resonance"],
)


# ============================================================
# S2: 产品风险等级与策略匹配分析
# ============================================================
S2_PRODUCT_RISK_STRATEGY = ScenarioView(
    scenario_id="datahub_s2_risk_strategy",
    scenario_name="产品风险等级与策略匹配分析",
    description=(
        "基于 zysc_ptl_info_records 构建风险等级×策略类型交叉矩阵，"
        "分析不同风险等级产品的估值方法分布、管理人集中度、产品期限特征，"
        "识别风险-策略不匹配的潜在问题。"
    ),
    tables_involved=["zysc_ptl_info_records"],
    analysis_dimensions=[
        "风险等级分布", "策略类型分布", "风险×策略交叉矩阵",
        "估值方法分布", "产品期限分析", "管理人产品数量",
    ],
    query_template={
        "collection": "zysc_ptl_info_records",
        "pipelines": {
            "risk_strategy_matrix": [
                {"$group": {
                    "_id": {"risk": "$风险等级", "strategy": "$策略类型"},
                    "count": {"$sum": 1},
                    "products": {"$addToSet": "$产品简称"},
                }},
                {"$sort": {"count": -1}},
            ],
            "valuation_by_risk": [
                {"$group": {
                    "_id": {"risk": "$风险等级", "valuation": "$估值方法"},
                    "count": {"$sum": 1},
                }},
                {"$sort": {"_id.risk": 1, "count": -1}},
            ],
            "maturity_analysis": [
                {"$match": {"产品到期日": {"$ne": None}}},
                {"$project": {
                    "产品代码": 1, "产品简称": 1, "风险等级": 1,
                    "产品起息日": 1, "产品到期日": 1,
                }},
                {"$sort": {"产品到期日": 1}},
            ],
            "manager_product_count": [
                {"$group": {
                    "_id": "$管理人",
                    "product_count": {"$sum": 1},
                    "risk_levels": {"$addToSet": "$风险等级"},
                    "strategies": {"$addToSet": "$策略类型"},
                }},
                {"$sort": {"product_count": -1}},
            ],
        },
    },
    expected_output_schema={
        "risk_strategy_matrix": "风险等级×策略类型→产品数量+产品列表",
        "valuation_by_risk": "风险等级×估值方法→产品数量",
        "maturity_analysis": "产品期限→代码+简称+风险+起息日+到期日",
        "manager_product_count": "管理人→产品数+风险等级集合+策略集合",
    },
    analysis_narrative=(
        "35个理财产品中，风险等级以R3平衡型为主（{r3_count}个，{r3_pct}%），"
        "策略类型以FOF配置（{fof_count}个）和CTA趋势（{cta_count}个）为主。"
        "估值方法以市值法（{mv_count}个）为绝对主流。"
        "风险-策略交叉分析显示：R3产品中{r3_strategy_diversity}种策略并存，"
        "管理人{top_manager}管理{top_manager_count}个产品，集中度偏高。"
    ),
    related_profiles=["l2_data_hub", "datahub_product_bridge"],
)


# ============================================================
# S3: 持有人结构变迁与集中度监控
# ============================================================
S3_HOLDER_STRUCTURE_EVOLUTION = ScenarioView(
    scenario_id="datahub_s3_holder_evolution",
    scenario_name="持有人结构变迁与集中度监控",
    description=(
        "基于 zysc_ptl_holder_records 的五期数据（2025-06-30 / 2025-12-31 / 2026-03-31 / 2026-06-30 / 2026-09-30），"
        "分析产品持有人结构变迁（机构/个人占比变化趋势）、前十集中度Top10、"
        "份额变动幅度，识别集中度风险和流动性风险信号。"
    ),
    tables_involved=["zysc_ptl_holder_records"],
    analysis_dimensions=[
        "多期持有人结构变迁", "前十集中度Top10", "机构/个人占比变化趋势",
        "份额变动幅度", "集中度风险信号", "跨期漂移分析",
    ],
    query_template={
        "collection": "zysc_ptl_holder_records",
        "pipelines": {
            "period_comparison": [
                {"$group": {
                    "_id": "$生效日期",
                    "avg_institutional_share": {"$avg": "$机构份额"},
                    "avg_personal_share": {"$avg": "$个人份额"},
                    "avg_top10_share": {"$avg": "$前十份额"},
                    "total_institutional_amount": {"$sum": "$机构金额"},
                    "total_personal_amount": {"$sum": "$个人金额"},
                    "count": {"$sum": 1},
                }},
                {"$sort": {"_id": 1}},
            ],
            "top10_concentration": [
                {"$match": {"生效日期": "2026-09-30"}},
                {"$project": {
                    "产品代码": 1,
                    "前十份额": 1,
                    "个人份额": 1,
                    "机构份额": 1,
                    "total_share": {"$add": ["$个人份额", "$机构份额"]},
                    "concentration": {"$cond": [
                        {"$gt": [{"$add": ["$个人份额", "$机构份额"]}, 0]},
                        {"$divide": ["$前十份额", {"$add": ["$个人份额", "$机构份额"]}]},
                        0,
                    ]},
                }},
                {"$sort": {"concentration": -1}},
                {"$limit": 10},
            ],
            "structure_change": [
                {"$project": {
                    "产品代码": 1, "生效日期": 1,
                    "机构份额": 1, "个人份额": 1,
                    "total": {"$add": ["$机构份额", "$个人份额"]},
                    "inst_ratio": {"$cond": [
                        {"$gt": [{"$add": ["$机构份额", "$个人份额"]}, 0]},
                        {"$divide": ["$机构份额", {"$add": ["$机构份额", "$个人份额"]}]},
                        0,
                    ]},
                }},
                {"$sort": {"产品代码": 1, "生效日期": 1}},
            ],
        },
    },
    expected_output_schema={
        "period_comparison": "生效日期→平均份额+总金额+产品数",
        "top10_concentration": "产品代码→前十份额+总份额+集中度比率(Top10)",
        "structure_change": "产品代码×生效日期→机构/个人份额+机构占比",
    },
    analysis_narrative=(
        "五期持有人结构变迁分析：机构份额均值从{h1_avg_inst:,.0f}（2025H1）变化至{h5_avg_inst:,.0f}（2026Q3），"
        "个人份额均值从{h1_avg_personal:,.0f}变化至{h5_avg_personal:,.0f}，跨期机构占比漂移平均±0.7%。"
        "最新期（2026-09-30）前十集中度最高的产品为{top_concentration_product}，集中度{top_concentration:.1%}。"
        "集中度>50%的产品有{high_concentration_count}个，需关注流动性风险。"
    ),
    related_profiles=["l2_data_hub", "datahub_product_bridge"],
)


# ============================================================
# S4: 数据导入质量审计看板
# ============================================================
S4_IMPORT_QUALITY_AUDIT = ScenarioView(
    scenario_id="datahub_s4_import_audit",
    scenario_name="数据导入质量审计看板",
    description=(
        "基于 3 张 batches 表（subject_risk/zysc_ptl_info/zysc_ptl_holder）"
        "构建数据导入质量审计视图，分析成功率、失败原因、耗时分布、批次时间线，"
        "识别上游接口健康度问题和数据完整性风险。"
    ),
    tables_involved=[
        "subject_risk_import_batches",
        "zysc_ptl_info_import_batches",
        "zysc_ptl_holder_import_batches",
    ],
    analysis_dimensions=[
        "各表导入成功率", "失败原因分布", "耗时分布",
        "批次时间线", "孤儿批次检测",
    ],
    query_template={
        "collections": [
            "subject_risk_import_batches",
            "zysc_ptl_info_import_batches",
            "zysc_ptl_holder_import_batches",
        ],
        "pipelines": {
            "status_distribution": [
                {"$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "avg_duration": {"$avg": "$duration_ms"},
                }},
                {"$sort": {"count": -1}},
            ],
            "failure_analysis": [
                {"$match": {"status": {"$ne": "success"}}},
                {"$project": {
                    "batch_id": 1, "status": 1,
                    "started_at": 1, "duration_ms": 1,
                    "upstream_error": {"$ifNull": ["$upstream_message", "N/A"]},
                    "total_returned": 1, "failed": 1,
                }},
                {"$sort": {"started_at": -1}},
            ],
            "batch_timeline": [
                {"$project": {
                    "batch_id": 1, "status": 1,
                    "started_at": 1, "duration_ms": 1,
                    "inserted": 1, "updated": 1, "failed": 1,
                    "total_returned": 1,
                }},
                {"$sort": {"started_at": -1}},
            ],
        },
    },
    expected_output_schema={
        "status_distribution": "状态→批次计数+平均耗时",
        "failure_analysis": "失败批次→ID+状态+时间+上游错误信息",
        "batch_timeline": "时间线→批次ID+状态+耗时+操作计数",
    },
    analysis_narrative=(
        "数据导入质量审计：共{total_batches}个批次，"
        "成功率{success_rate:.1%}（success {success_count}/{total_batches}），"
        "partial {partial_count}个，failed_upstream {failed_count}个。"
        "failed_upstream批次集中在{failed_table}表，需排查上游接口状态。"
        "平均导入耗时{avg_duration:.0f}ms，{slow_batch}表耗时偏长。"
    ),
    related_profiles=["l2_data_hub", "datahub_dataflow_crisis"],
)


# ============================================================
# S5: 风险主体-产品持仓交叉预警
# ============================================================
S5_RISK_PRODUCT_CROSS_ALERT = ScenarioView(
    scenario_id="datahub_s5_risk_product_alert",
    scenario_name="风险主体-产品持仓交叉预警",
    description=(
        "将 subject_risk_records 的高风险主体与 zysc_ptl_info_records 的产品管理人"
        "进行交叉匹配，识别高风险主体管理下的产品风险敞口。"
        "结合 zysc_ptl_holder_records 分析高风险关联产品的持有人集中度。"
    ),
    tables_involved=[
        "subject_risk_records",
        "zysc_ptl_info_records",
        "zysc_ptl_holder_records",
    ],
    analysis_dimensions=[
        "高风险主体关联产品", "产品风险等级叠加",
        "持有人集中度", "风险传导路径",
    ],
    query_template={
        "steps": {
            "step1_high_risk_subjects": {
                "collection": "subject_risk_records",
                "pipeline": [
                    {"$match": {"risk_signal_level": "高"}},
                    {"$group": {
                        "_id": "$subject_name",
                        "risk_count": {"$sum": 1},
                        "rule_categories": {"$addToSet": "$rule_large"},
                        "latest_date": {"$max": "$biz_date"},
                    }},
                    {"$sort": {"risk_count": -1}},
                ],
            },
            "step2_products_by_manager": {
                "collection": "zysc_ptl_info_records",
                "pipeline": [
                    {"$group": {
                        "_id": "$管理人",
                        "products": {
                            "$push": {
                                "code": "$产品代码",
                                "name": "$产品简称",
                                "risk": "$风险等级",
                                "strategy": "$策略类型",
                            }
                        },
                        "product_count": {"$sum": 1},
                    }},
                ],
                "comment": "提取管理人→产品映射，在应用层与高风险主体交叉",
            },
            "step3_holder_risk_overlay": {
                "collection": "zysc_ptl_holder_records",
                "pipeline": [
                    {"$match": {"生效日期": "2025-12-31"}},
                    {"$lookup": {
                        "from": "zysc_ptl_info_records",
                        "localField": "产品代码",
                        "foreignField": "产品代码",
                        "as": "product_info",
                    }},
                    {"$unwind": {"path": "$product_info", "preserveNullAndEmpty": True}},
                    {"$project": {
                        "产品代码": 1,
                        "前十份额": 1,
                        "机构份额": 1,
                        "个人份额": 1,
                        "产品风险等级": "$product_info.风险等级",
                        "管理人": "$product_info.管理人",
                        "策略类型": "$product_info.策略类型",
                    }},
                    {"$sort": {"前十份额": -1}},
                ],
            },
        },
    },
    expected_output_schema={
        "step1_high_risk_subjects": "高风险主体→风险次数+规则类别+最新日期",
        "step2_products_by_manager": "管理人→产品列表(代码+简称+风险+策略)",
        "step3_holder_risk_overlay": "产品代码→份额+风险等级+管理人+策略",
    },
    analysis_narrative=(
        "风险交叉预警分析：{high_risk_count}个高风险主体中，"
        "{overlap_count}个主体的名称与产品管理人存在潜在关联。"
        "高风险关联产品共{risk_product_count}个，"
        "其中R4/R5高风险产品{high_risk_product_count}个。"
        "最新期持有人数据显示，高风险关联产品的机构份额均值{avg_inst:,.0f}，"
        "前十集中度均值{avg_concentration:.1%}。"
    ),
    related_profiles=[
        "l2_data_hub", "datahub_risk_subject",
        "datahub_product_bridge", "datahub_risk_resonance",
    ],
)


# ============================================================
# 场景视图注册表
# ============================================================
DATAHUB_SCENARIO_VIEWS = {
    "datahub_s1_high_risk_scan": S1_HIGH_RISK_SUBJECT_SCAN,
    "datahub_s2_risk_strategy": S2_PRODUCT_RISK_STRATEGY,
    "datahub_s3_holder_evolution": S3_HOLDER_STRUCTURE_EVOLUTION,
    "datahub_s4_import_audit": S4_IMPORT_QUALITY_AUDIT,
    "datahub_s5_risk_product_alert": S5_RISK_PRODUCT_CROSS_ALERT,
}


def get_all_scenario_views() -> dict:
    """获取所有 data_hub 场景视图"""
    return DATAHUB_SCENARIO_VIEWS


def execute_scenario(scenario_id: str, db) -> dict:
    """执行指定场景的查询并返回结果

    Args:
        scenario_id: 场景标识
        db: MongoDB database instance

    Returns:
        dict: {pipeline_name: results_list}
    """
    scenario = DATAHUB_SCENARIO_VIEWS.get(scenario_id)
    if not scenario:
        return {"error": f"场景 {scenario_id} 不存在"}

    results = {}
    qt = scenario.query_template

    # 单表场景（pipelines 在顶层）
    if "collection" in qt and "pipelines" in qt:
        col = qt["collection"]
        for name, pipeline in qt["pipelines"].items():
            try:
                results[name] = list(db[col].aggregate(pipeline))
            except Exception as e:
                results[name] = {"error": str(e)}

    # 多表场景（pipelines 按表分别定义）
    elif "collections" in qt and "pipelines" in qt:
        for col in qt["collections"]:
            col_results = {}
            for name, pipeline in qt["pipelines"].items():
                try:
                    col_results[name] = list(db[col].aggregate(pipeline))
                except Exception as e:
                    col_results[name] = {"error": str(e)}
            results[col] = col_results

    # 多步骤场景（steps）
    elif "steps" in qt:
        for step_name, step_cfg in qt["steps"].items():
            col = step_cfg["collection"]
            pipeline = step_cfg["pipeline"]
            try:
                results[step_name] = list(db[col].aggregate(pipeline))
            except Exception as e:
                results[step_name] = {"error": str(e)}

    return results

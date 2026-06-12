"""
通用数据接入域(Data Hub Domain) - L1静态画像定义
覆盖：主体观点风险记录、产品信息记录、产品持有人汇总记录 及对应导入批次表，共6张表
"""
from ..models import DomainOverview, FieldProfile, TableProfile


DOMAIN_OVERVIEW = DomainOverview(
    domain_code="data_hub",
    domain_name="通用数据接入域",
    description=(
        "管理通过通用数据接入中心（Data Hub）从上游API拉取并落地的业务数据。"
        "包含3张业务记录表（主体观点风险、产品信息、产品持有人汇总）和3张导入批次表，"
        "是外部数据进入投研系统的统一入口，支持增量拉取、批次溯源、质量审计。"
    ),
    table_count=6,
    tables=[
        "subject_risk_records",
        "subject_risk_import_batches",
        "zysc_ptl_info_records",
        "zysc_ptl_info_import_batches",
        "zysc_ptl_holder_records",
        "zysc_ptl_holder_import_batches",
    ],
    core_scenarios=[
        "主体舆情风险信号的接入与分级预警",
        "理财产品/资管产品主数据的全量同步",
        "产品持有人结构的定期更新与机构/个人占比分析",
        "数据导入批次的溯源与质量审计",
        "跨域关联：风险主体与持仓资产的交叉监控",
    ],
    key_entities=[
        "risk_id", "产品代码", "_holder_row_uid",
        "batch_id", "subject_name", "管理人",
    ],
)


TABLE_PROFILES = {
    # ───────────────────── 主体观点风险记录 ─────────────────────
    "subject_risk_records": TableProfile(
        table_name="subject_risk_records",
        domain="data_hub",
        display_name="主体观点风险记录表",
        purpose=(
            "记录上游 adm_subject_opinion_risk_stats 接口的风险舆情数据。"
            "每条记录对应一个风险事件（risk_id），包含主体名称、风险等级（高/黄/低）、"
            "信号描述、三级规则分类（rule_large/medium/small）、行业分类、省份、"
            "企业性质、白名单标识（is_approved_investment_quota_client 等）共22个业务字段。"
            "是投研系统对发行人/机构风险事件进行监控、预警和合规审查的核心数据源。"
        ),
        distribution=(
            "risk_signal_level 以「黄」色（关注级）为主（约50%），「高」风险约30%，"
            "「低」风险约20%；enterprise_nature 以国有企业（约53%）和民营企业（约35%）为主，"
            "少量混合所有制；industry_classification_gb 涵盖房地产业、金融业、建筑业、"
            "信息技术、制造业等8+行业；affiliated_province 以广东省（约58%）为主，"
            "其次为北京市（25%）、上海市、江苏省、浙江省；"
            "rule_large 大类6种（客户经营/融资/信用/合规/舆情/财务），"
            "rule_medium 中类12+种，rule_small 小类15+种。"
            "高风险集中于房地产企业（万科/碧桂园/恒大），与主体域 dwd_isr_institution 18个主体完全匹配。"
        ),
        trend=(
            "风险信号量与市场波动周期正相关：股市大幅调整期、债券违约高发期、"
            "政策收紧期风险信号量显著增加；工作日信号量高于周末；"
            "每季度财报披露期前后通常出现信号高峰。"
        ),
        anomaly=(
            "需关注：同一主体短期内连续触发多条高风险信号（可能为系统性风险前兆）；"
            "rule_large/rule_medium/rule_small 分类为空（上游数据质量异常）；"
            "signal_dascribe 中出现极端金额或负面事件描述；"
            "is_parent_bank_veto_client='是' 的主体新增风险（否决类客户仍有业务敞口）。"
        ),
        scenarios=[
            "查询高风险等级的主体列表",
            "按省份/行业/企业性质统计风险分布",
            "查询某主体名称的历史风险事件时间线",
            "筛选否决类/非白名单客户中仍触发新风险的主体",
            "统计各规则大类的风险数量趋势",
            "关联主体域查询风险主体的债券信息",
        ],
        key_fields=[
            "risk_id", "biz_date", "subject_name", "risk_signal_level",
            "signal_dascribe", "rule_large", "rule_medium", "rule_small",
            "enterprise_nature", "industry_classification_gb", "affiliated_province",
        ],
        primary_keys=["risk_id"],
        foreign_keys={"subject_name": "dwd_isr_institution.ISR_NM"},
        field_profiles=[
            FieldProfile(field_name="risk_id", display_name="风险事件ID", data_type="string",
                definition="上游风险事件的唯一标识，格式为日期+流水号", example_values=["20250827DG39170410872248"],
                is_primary_key=True, sensitivity_level="internal",
                tags=["主键", "检索键"]),
            FieldProfile(field_name="biz_date", display_name="业务日期", data_type="date",
                definition="风险事件发生的业务日期", example_values=["2025-08-27", "2025-09-15"],
                is_time_series=True, sensitivity_level="public",
                tags=["排序键", "维度"]),
            FieldProfile(field_name="subject_name", display_name="主体名称", data_type="string",
                definition="风险事件关联的法人主体全称，与主体域ISR_NM语义对齐",
                example_values=["万科企业股份有限公司", "碧桂园控股有限公司"],
                is_foreign_key=True, references="dwd_isr_institution.ISR_NM",
                association_chains=["subject_name → dwd_isr_institution.ISR_NM → dwd_ast_info.ISSUER_ID"],
                sensitivity_level="public", tags=["检索键", "维度", "外键"]),
            FieldProfile(field_name="risk_signal_level", display_name="风险信号等级", data_type="enum",
                definition="风险事件的分级标签，决定是否触发预警和行动",
                enum_values={"高": "高风险，需立即关注", "黄": "关注级，持续监控", "低": "低风险，常规记录"},
                example_values=["高", "黄", "低"],
                sensitivity_level="internal", tags=["维度", "聚合键", "预警键"]),
            FieldProfile(field_name="signal_dascribe", display_name="信号描述", data_type="string",
                definition="风险事件的自然语言描述，含评级变动、舆情事件等具体内容",
                example_values=["主体信用评级由AA-下调至A+"],
                sensitivity_level="internal", tags=["文本"]),
            FieldProfile(field_name="rule_large", display_name="规则大类", data_type="enum",
                definition="风险事件的顶层分类，含6种大类",
                enum_values={"客户经营情况": "经营维度", "客户融资情况": "融资维度",
                    "客户信用情况": "信用维度", "客户合规情况": "合规维度",
                    "客户舆情情况": "舆情维度", "客户财务情况": "财务维度"},
                example_values=["客户经营情况", "客户信用情况"],
                sensitivity_level="internal", tags=["维度", "聚合键"]),
            FieldProfile(field_name="rule_medium", display_name="规则中类", data_type="enum",
                definition="风险事件的二级分类，含12+种中类",
                example_values=["司法及行政处罚事件", "评级变动事件"],
                sensitivity_level="internal", tags=["维度"]),
            FieldProfile(field_name="rule_small", display_name="规则小类", data_type="enum",
                definition="风险事件的三级细分，含15+种小类",
                example_values=["企业主体评级被下调或展望调为负面"],
                sensitivity_level="internal", tags=["维度"]),
            FieldProfile(field_name="enterprise_nature", display_name="企业性质", data_type="enum",
                definition="主体法人的所有制性质",
                enum_values={"国有企业": "国有控股", "民营企业": "民营控股", "混合所有制": "国有+民营"},
                example_values=["混合所有制", "国有企业", "民营企业"],
                sensitivity_level="public", tags=["维度", "聚合键"]),
            FieldProfile(field_name="industry_classification_gb", display_name="国标行业分类", data_type="string",
                definition="按国标GB/T 4754的行业分类，含一级和二级",
                example_values=["房地产业-房地产开发经营", "金融业-资本市场服务"],
                sensitivity_level="public", tags=["维度", "聚合键"]),
            FieldProfile(field_name="affiliated_province", display_name="所属省份", data_type="string",
                definition="主体法人注册地所在省份",
                example_values=["广东省", "北京市", "上海市"],
                sensitivity_level="public", tags=["维度", "聚合键"]),
        ],
    ),

    # ───────────────────── 主体风险导入批次 ─────────────────────
    "subject_risk_import_batches": TableProfile(
        table_name="subject_risk_import_batches",
        domain="data_hub",
        display_name="主体风险导入批次表",
        purpose=(
            "记录每次从上游拉取主体风险数据的导入批次元数据。"
            "含批次ID、状态（success/partial/failed_*）、起止时间、耗时、"
            "请求参数、上游响应码/消息、插入/更新/跳过/失败计数等，"
            "是数据溯源和质量审计的关键凭证。"
        ),
        distribution=(
            "status 以 success 为主（>90%），partial/failed 偶发；"
            "duration_ms 通常 500-5000ms；total_returned 与 rownum 参数相关。"
        ),
        trend=(
            "按日/周定期导入；导入量随市场事件密度波动；"
            "failed 批次通常伴随上游接口超时或限流。"
        ),
        anomaly=(
            "需关注：连续 failed 批次（上游接口可能故障）；"
            "total_returned=0 但 status=success（空数据但仍标记成功）；"
            "duration_ms 异常偏长（>60s，可能超时重试）。"
        ),
        scenarios=[
            "查询最近10次导入批次及状态",
            "统计导入成功率和平均耗时",
            "定位失败批次的上游错误信息",
        ],
        key_fields=[
            "batch_id", "status", "started_at", "duration_ms",
            "total_returned", "inserted", "updated", "failed",
        ],
        primary_keys=["batch_id"],
    ),

    # ───────────────────── 产品信息记录 ─────────────────────
    "zysc_ptl_info_records": TableProfile(
        table_name="zysc_ptl_info_records",
        domain="data_hub",
        display_name="产品信息记录表",
        purpose=(
            "从上游 ZYSC_DWD_PTL_INFO 拉取的理财产品/资管产品全量主数据。"
            "含52个字段：产品代码（主键）、简称、名称、产品性质（理财/资管/基金等）、"
            "产品类型代码、系列/细分、风险等级、估值方法（市值法/摊余成本法等）、"
            "管理人、托管人、投资经理、币种、策略类型、开放频率、运行方式、"
            "三类基准（市场/合约/内部）、起息日、到期日、建仓期等。"
            "是产品域（dwd_ptl_info）的外部数据补充源。"
        ),
        distribution=(
            "产品性质 全部为「理财产品」（100%），来自浙银理财；"
            "风险等级 以 R3（平衡）为主（63%），R2 稳健型 14%，R4 进取型 17%，R1 保守型 6%；"
            "估值方法 以市值法为主（91%），少量摊余成本法（9%，主要为货币类）；"
            "币种 全部为人民币；策略类型覆盖固收+、混合策略、指数增强、FOF配置、CTA趋势、QDII海外等8种；"
            "产品系列 涵盖璟衡、珠衡、涌盈、稳泰、优选等5+系列。"
            "35个产品代码与产品域 dwd_ptl_info 100%匹配。"
        ),
        trend=(
            "产品数量逐季增长（新发产品持续入库）；"
            "到期产品仍保留记录（数据日期标记）；"
            "全量拉取时受上游 pageMsg 限制需分页。"
        ),
        anomaly=(
            "需关注：产品代码重复（可能为主键冲突）；"
            "产品到期日早于起息日（上游数据错误）；"
            "管理人/托管人字段为空（必填字段缺失）；"
            "合约基准上下限倒挂（上限<下限）。"
        ),
        scenarios=[
            "查询所有理财产品并按系列分组",
            "按风险等级筛选R2稳健型产品",
            "统计各管理人的产品数量Top10",
            "筛选即将在30天内到期的产品",
            "对比市值法和摊余成本法的产品数量",
            "查询某投资经理管理的所有产品",
        ],
        key_fields=[
            "产品代码", "产品简称", "产品名称", "产品性质", "风险等级",
            "估值方法", "管理人", "托管人", "投资经理", "币种",
            "策略类型", "产品起息日", "产品到期日",
        ],
        primary_keys=["产品代码"],
        foreign_keys={"产品代码": "dwd_ptl_info.PORT_ID", "管理人": "dwd_isr_institution.ISR_NM"},
        field_profiles=[
            FieldProfile(field_name="产品代码", display_name="产品代码", data_type="string",
                definition="理财产品唯一标识，与内部产品域PORT_ID对齐",
                example_values=["PTL_001", "PTL_015"],
                is_primary_key=True, is_foreign_key=True, references="dwd_ptl_info.PORT_ID",
                association_chains=["产品代码 → dwd_ptl_info.PORT_ID → dwd_ptl_ast_hld.AST_CD"],
                sensitivity_level="internal", tags=["主键", "检索键", "外键"]),
            FieldProfile(field_name="产品简称", display_name="产品简称", data_type="string",
                definition="产品简短名称，用于显示和报表", example_values=["稳健收益1号", "进取成长1号"],
                sensitivity_level="public", tags=["检索键"]),
            FieldProfile(field_name="产品名称", display_name="产品全称", data_type="string",
                definition="产品完整名称，含管理人+系列+期数",
                example_values=["浙银理财稳泰2024年第1期"],
                sensitivity_level="public", tags=["检索键"]),
            FieldProfile(field_name="产品性质", display_name="产品性质", data_type="enum",
                definition="产品所属类别，当前数据全部为理财产品",
                enum_values={"理财产品": "银行理财子公司发行", "资管产品": "资管计划", "基金": "公募基金"},
                sensitivity_level="public", tags=["维度"]),
            FieldProfile(field_name="风险等级", display_name="风险等级", data_type="enum",
                definition="产品风险评级，R1最低R5最高",
                enum_values={"R1": "保守型", "R2": "稳健型", "R3": "平衡型", "R4": "进取型", "R5": "激进型"},
                example_values=["R2", "R3", "R4"],
                sensitivity_level="public", tags=["维度", "聚合键", "预警键"]),
            FieldProfile(field_name="估值方法", display_name="估值方法", data_type="enum",
                definition="产品净值计算所采用的估值方法",
                enum_values={"市值法": "按市价估值", "摊余成本法": "按成本推推收益"},
                sensitivity_level="internal", tags=["维度"]),
            FieldProfile(field_name="管理人", display_name="管理人", data_type="string",
                definition="产品管理方，当前全部为浙银理财",
                is_foreign_key=True, references="dwd_isr_institution.ISR_NM",
                sensitivity_level="public", tags=["维度", "外键"]),
            FieldProfile(field_name="托管人", display_name="托管人", data_type="string",
                definition="产品资金托管银行", example_values=["交通银行", "招商银行", "工商银行"],
                sensitivity_level="public", tags=["维度"]),
            FieldProfile(field_name="投资经理", display_name="投资经理", data_type="string",
                definition="产品负责投资管理的基金经理姓名",
                example_values=["陈志华", "李明达"],
                sensitivity_level="internal", tags=["维度"]),
            FieldProfile(field_name="币种", display_name="币种", data_type="enum",
                definition="产品计价货币，当前全部为人民币",
                enum_values={"人民币": "CNY"}, sensitivity_level="public", tags=["维度"]),
            FieldProfile(field_name="策略类型", display_name="策略类型", data_type="enum",
                definition="产品投资策略分类",
                enum_values={"纯债策略": "固收类", "固收+": "增强收益", "混合策略": "多资产",
                    "指数增强": "量化", "FOF配置": "基金中基金", "CTA趋势": "商品", "QDII海外": "海外"},
                sensitivity_level="internal", tags=["维度", "聚合键"]),
            FieldProfile(field_name="产品起息日", display_name="产品起息日", data_type="date",
                definition="产品开始计息的日期", example_values=["2024-04-15"],
                sensitivity_level="public", tags=["排序键"]),
            FieldProfile(field_name="产品到期日", display_name="产品到期日", data_type="date",
                definition="产品到期终止日期，开放式产品可能为空",
                example_values=["2024-10-12"],
                sensitivity_level="public", tags=["排序键", "预警键"]),
        ],
    ),

    # ───────────────────── 产品信息导入批次 ─────────────────────
    "zysc_ptl_info_import_batches": TableProfile(
        table_name="zysc_ptl_info_import_batches",
        domain="data_hub",
        display_name="产品信息导入批次表",
        purpose=(
            "记录每次从上游拉取产品信息的导入批次元数据。"
            "结构与主体风险批次表一致，支持溯源与审计。"
        ),
        distribution=(
            "status 以 success 为主；因受 pageMsg 限制，"
            "partial 状态（数据截断）比风险批次更常见。"
        ),
        trend=(
            "导入频率通常为周/月级别；全量拉取时 total_returned 较大。"
        ),
        anomaly=(
            "需关注：total_returned 突然减少（上游数据源变动）；"
            "inserted=0 且 updated=0（可能参数 PROD_CDS 筛选过严）。"
        ),
        scenarios=[
            "查询产品信息最近导入时间",
            "统计成功导入率",
        ],
        key_fields=[
            "batch_id", "status", "started_at", "duration_ms",
            "total_returned", "inserted", "updated", "failed",
        ],
        primary_keys=["batch_id"],
    ),

    # ───────────────────── 产品持有人汇总记录 ─────────────────────
    "zysc_ptl_holder_records": TableProfile(
        table_name="zysc_ptl_holder_records",
        domain="data_hub",
        display_name="产品持有人汇总记录表",
        purpose=(
            "从上游 ZYSC_DWD_PTL_HOLDER_SUMMARY 拉取的产品持有人结构数据。"
            "复合主键（产品代码+生效日期），含前十份额/金额、个人份额/金额、"
            "机构份额/金额、数据来源、导入方法等13个字段。"
            "是产品域持有人汇总表（dwd_ptl_holder_summary）的外部补充数据源，"
            "支撑机构/个人持仓占比分析和集中度监控。"
        ),
        distribution=(
            "机构份额与个人份额呈现明显两极分化：机构占比范围31%-86%，均值约57%；"
            "R1/R2低风险产品个人占比偏高（40-60%），R4进取型产品机构占比偏高（70-86%）；"
            "前十份额占比在25%-85%之间，反映产品持有人集中度差异较大；"
            "按五期存储（2025-06-30、2025-12-31、2026-03-31、2026-06-30、2026-09-30），共175条（35产品×5期），"
            "支持季度级持有人结构变迁分析，跨期机构占比漂移平均±0.7%，范围-23%~+25%；"
            "数据来源 全部为 ZYSC，导入方法 API。"
        ),
        trend=(
            "持有人数据按季/半年更新（跟随定期报告节奏）；"
            "同一产品多期持有人数据可追溯结构变迁。"
        ),
        anomaly=(
            "需关注：前十份额占比>95%（极端集中，流动性风险）；"
            "机构份额或个人份额为负数（数据异常）；"
            "同一产品同一生效日期存在多条记录（复合键冲突）；"
            "生效日期跨度异常（如未来日期）。"
        ),
        scenarios=[
            "查询某产品的持有人结构（机构vs个人）",
            "统计机构占比最高的产品Top10",
            "对比两期持有人结构变化",
            "筛选前十集中度>80%的高集中产品",
            "按数据来源分组统计",
        ],
        key_fields=[
            "_holder_row_uid", "产品代码", "生效日期",
            "前十份额", "前十金额", "个人份额", "个人金额",
            "机构份额", "机构金额", "数据来源",
        ],
        primary_keys=["_holder_row_uid"],
        foreign_keys={"产品代码": "zysc_ptl_info_records.产品代码"},
        field_profiles=[
            FieldProfile(field_name="_holder_row_uid", display_name="持有人行唯一ID", data_type="string",
                definition="复合主键，格式为“产品代码|生效日期”，确保每行唯一",
                example_values=["PTL_001|2025-06-30", "PTL_001|2025-12-31"],
                is_primary_key=True, sensitivity_level="internal",
                tags=["主键"]),
            FieldProfile(field_name="产品代码", display_name="产品代码", data_type="string",
                definition="关联的产品标识，桥接zysc_ptl_info_records",
                example_values=["PTL_001", "PTL_015"],
                is_foreign_key=True, references="zysc_ptl_info_records.产品代码",
                association_chains=["产品代码 → zysc_ptl_info_records.产品代码 → dwd_ptl_info.PORT_ID",
                    "产品代码 → zysc_ptl_info_records.风险等级"],
                sensitivity_level="internal", tags=["检索键", "外键"]),
            FieldProfile(field_name="生效日期", display_name="生效日期", data_type="date",
                definition="持有人数据的报告时点，通常为季末/半年末",
                example_values=["2025-06-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"],
                is_time_series=True, sensitivity_level="public",
                tags=["排序键", "维度"]),
            FieldProfile(field_name="前十份额", display_name="前十名持有人份额", data_type="number",
                definition="产品前十大持有人的合计份额，反映集中度",
                unit="份", example_values=["1000381788.07"],
                sensitivity_level="internal", tags=["度量", "预警键"]),
            FieldProfile(field_name="前十金额", display_name="前十名持有人金额", data_type="number",
                definition="前十大持有人的合计持有金额",
                unit="元", example_values=["983913331.33"],
                sensitivity_level="internal", tags=["度量"]),
            FieldProfile(field_name="个人份额", display_name="个人投资者份额", data_type="number",
                definition="个人投资者合计持有份额",
                unit="份", example_values=["1162447661.95"],
                sensitivity_level="internal", tags=["度量"]),
            FieldProfile(field_name="个人金额", display_name="个人投资者金额", data_type="number",
                definition="个人投资者合计持有金额",
                unit="元", example_values=["1143311248.97"],
                sensitivity_level="internal", tags=["度量"]),
            FieldProfile(field_name="机构份额", display_name="机构投资者份额", data_type="number",
                definition="机构投资者合计持有份额",
                unit="份", example_values=["666738273.45"],
                sensitivity_level="internal", tags=["度量"]),
            FieldProfile(field_name="机构金额", display_name="机构投资者金额", data_type="number",
                definition="机构投资者合计持有金额",
                unit="元", example_values=["655762313.53"],
                sensitivity_level="internal", tags=["度量"]),
            FieldProfile(field_name="数据来源", display_name="数据来源", data_type="enum",
                definition="持有人数据的上游来源标识",
                enum_values={"ZYSC": "浙商银行数据中台"},
                sensitivity_level="public", tags=["维度"]),
        ],
    ),

    # ───────────────────── 产品持有人导入批次 ─────────────────────
    "zysc_ptl_holder_import_batches": TableProfile(
        table_name="zysc_ptl_holder_import_batches",
        domain="data_hub",
        display_name="产品持有人导入批次表",
        purpose=(
            "记录每次从上游拉取产品持有人数据的导入批次元数据。"
            "结构与其他批次表一致，支持溯源与审计。"
        ),
        distribution=(
            "批次数量较少（持有人数据更新频率低）；"
            "status 以 success 为主。"
        ),
        trend=(
            "导入频率通常为季度级别（跟随定期报告披露节奏）。"
        ),
        anomaly=(
            "需关注：长期未更新（>1季度无新批次，可能为上游接口变更或遗忘拉取）。"
        ),
        scenarios=[
            "查询持有人数据最近导入时间",
            "统计导入成功率",
        ],
        key_fields=[
            "batch_id", "status", "started_at", "duration_ms",
            "total_returned", "inserted", "updated", "failed",
        ],
        primary_keys=["batch_id"],
    ),
}

"""
L2 域内表间画像定义

按照 9 大数据域（资产/主体/产品/估值/交易/客户/风险/行情）的内部关联结构，
归纳每个域内的主从关系、一致性约束、分布特征、异常检测要点与典型业务场景。

注：销售域仅 1 张表（dwd_seller_info），不涉及域内多表关联，故未单独建立 L2 画像。
"""
from ..models import IntraDomainProfile


INTRA_DOMAIN_PROFILES = {
    # ============================================================
    # 1. 资产域 — 14 表，AST_CD / code 为核心主键
    # ============================================================
    "asset": IntraDomainProfile(
        profile_id="l2_asset",
        domain="asset",
        domain_name="资产域",
        tables_involved=[
            "dwd_ast_info", "dwd_ast_info_ch", "dwd_ast_info_zg",
            "dwd_ast_yield_info", "dwd_ast_cf_plan", "dwd_ast_pledge",
            "dwd_ast_party", "dwd_ast_exe_plan", "dwd_ast_fund_manager",
            "dwd_ast_bottom_raito", "dwd_ast_fiveclass", "dwd_ast_calc_rule",
            "assets", "asset_prices",
        ],
        structure=(
            "以 dwd_ast_info 为主表，通过 AST_CD 与其余 11 张子表形成 1:1 或 1:N 的星型放射结构。"
            "估值附加（_ch/_zg）为 1:1 扩展，收益率/现金流/行权计划/担保（_yield_info/_cf_plan/_exe_plan/_pledge）"
            "对债券类资产形成 1:N 时序明细；五级分类（_fiveclass）按评级机构形成 1:N，基金类专属表"
            "（_fund_manager/_bottom_raito）仅对 FUND/ABS 类型 AST_CD 存在。"
            "\n\n同时，assets 表作为组合管理系统的资产主数据，通过 code 主键与 asset_prices.asset_code "
            "形成 1:N 日频K线行情关联。dwd_ast_info.AST_CD 与 assets.code 在语义上等价，"
            "两套体系通过资产代码形成跨域桥接。"
        ),
        consistency=(
            "AST_CD 在 dwd_ast_info 必为唯一主键，子表 AST_CD 必须命中主表，预期匹配率 ≥ 95%。"
            "ast_type=BOND 的资产应在 _yield_info/_cf_plan 中存在；ast_type=FUND/ABS 才允许出现在 "
            "_fund_manager/_bottom_raito；中债/中证估值（_zg/_ch）的 BIZ_DT 必须与主表 last_biz_date 对齐，"
            "估值净价 + 应计利息 ≈ 全价（误差 < 0.5%）。"
        ),
        distribution=(
            "AST_CD 池常驻 12 个核心证券，类型分布约为 BOND 60% / EQUITY 17% / FUND 17% / ABS 6%。"
            "_yield_info 与 _cf_plan 按 BIZ_DT 形成日级或月级序列，债券到期收益率（YTM）集中在 1.8%~3.5% 区间，"
            "信用债加点（spread）随评级递增；_fiveclass 中正常类占比 > 90%，关注类与不良类占比反映组合信用质量。"
        ),
        anomaly=(
            "重点排查：①子表存在但主表缺失的孤儿 AST_CD；②同一资产在 _ch 与 _zg 估值价差 > 1% 的估值偏离；"
            "③_cf_plan 累计现金流与债券面额×票息一致性校验失败；④_fiveclass 跨评级机构等级差异 ≥ 2 档；"
            "⑤_pledge 质押率 > 100% 或质押到期日早于资产到期日；⑥行权计划中含权债到期日未触发行权状态。"
        ),
        scenarios=[
            "债券现金流预测与久期重定价",
            "中债/中证双源估值偏离监控",
            "底层穿透与基金资产分类核查",
            "信用债五级分类与评级一致性审查",
            "含权债行权日临近预警",
            "质押券释放与抵押覆盖率分析",
        ],
        join_keys={
            "AST_CD": "全域 12 表统一主关联键，连接资产基础信息与所有子表",
            "code": "assets 主表主键，与 asset_prices.asset_code 关联，语义等价于 AST_CD",
            "asset_code": "asset_prices 行情表的外键，关联 assets.code",
            "ISR_ID": "dwd_ast_info → 主体域 dwd_isr_institution 的发行人外键",
            "BIZ_DT": "_yield_info / _cf_plan / _ch / _zg / _fiveclass 的时序快照键",
            "PARTY_ID": "dwd_ast_party 关联方标识，用于关联方交易披露",
        },
    ),

    # ============================================================
    # 2. 主体域 — 3 表，ISR_ID 与 CNTP_ID 双核心
    # ============================================================
    "subject": IntraDomainProfile(
        profile_id="l2_subject",
        domain="subject",
        domain_name="主体域",
        tables_involved=[
            "dwd_isr_institution",
            "dwd_isr_institution_finance",
            "dwd_isr_trd_cntp",
        ],
        structure=(
            "dwd_isr_institution 为发行人/机构主表，以 ISR_ID 唯一标识 8 个核心机构。"
            "dwd_isr_institution_finance 通过 ISR_ID + RPT_DT（报告期）形成 1:N 财报序列；"
            "dwd_isr_trd_cntp 以 CNTP_ID 为主键，记录交易对手并通过 ISR_ID 反向链接到机构主表（部分对手为非机构客户）。"
        ),
        consistency=(
            "ISR_ID 在主表唯一，财报子表必须存在主表对应记录；财报字段需满足"
            "资产 = 负债 + 所有者权益（误差 < 0.1%）的会计恒等式；"
            "CNTP_ID 与 ISR_ID 不重叠，但交易对手如属机构发行人，应在 ISR_ID 字段冗余记录以支持反向穿透。"
            "财报 RPT_DT 应按 0331/0630/0930/1231 标准报告期分布。"
        ),
        distribution=(
            "8 个机构主体覆盖财政部、政策性银行、商业银行、保险、地产、新能源等行业，行业分布反映组合信用敞口。"
            "财报字段中总资产规模差异跨度大（地方城投 vs 国有大行差异可达 100x），ROE 集中在 5%~15%，"
            "资产负债率银行类 > 90%、产业类 50%~70%。CNTP_ID 池为 5 家头部券商/银行金融市场部。"
        ),
        anomaly=(
            "重点排查：①连续两期财报缺失或滞后超 90 天；②资产负债表勾稽失败；"
            "③净利润同比/环比波动 > 50% 的盈利异常；④经营性现金流连续 ≥ 2 期为负的造血能力恶化；"
            "⑤交易对手集中度过高（单一 CNTP 月度交易额占比 > 30%）；⑥关联方在 ISR_ID 与 CNTP_ID 双重身份下的潜在利益冲突。"
        ),
        scenarios=[
            "发行人财务画像与信用资质评估",
            "交易对手准入与集中度监控",
            "关联方交易识别与披露",
            "机构信用迁徙与下沉分析",
            "财报勾稽一致性审计",
        ],
        join_keys={
            "ISR_ID": "机构主表与财报子表的主关联键，并向资产域 dwd_ast_info 提供发行人外键",
            "CNTP_ID": "交易对手主键，向交易域 dwd_trn_* 提供对手方外键",
            "RPT_DT": "财报报告期，4 个标准季度时点",
        },
    ),

    # ============================================================
    # 3. 产品域 — 12 表，PORT_ID 为核心
    # ============================================================
    "product": IntraDomainProfile(
        profile_id="l2_product",
        domain="product",
        domain_name="产品域",
        tables_involved=[
            "dwd_ptl_info", "tag_ptl_info", "dwd_ptl_acc",
            "dwd_ptl_cedetail", "dwd_ptl_fee", "dwd_ptl_managers",
            "dwd_ptl_open_plan", "dwd_ptl_asset_config_info",
            "dwd_ptl_acct_bal", "dwd_ptl_ast_hld",
            "dwd_ptl_holder_summary", "dwd_cash_acc",
        ],
        structure=(
            "dwd_ptl_info 为产品主表（5 个 PORT_ID），tag_ptl_info 为 1:1 标签扩展。"
            "持仓相关：dwd_ptl_ast_hld（PORT_ID×AST_CD×BIZ_DT 1:N:N）、dwd_ptl_asset_config_info（资产配置规划）、"
            "dwd_ptl_acct_bal（账户余额日终快照）形成产品的资产侧画像；"
            "负债侧：dwd_ptl_holder_summary（持有人结构）、dwd_ptl_cedetail（申赎流水）；"
            "运营侧：dwd_ptl_acc（账户）、dwd_cash_acc（现金账户）、dwd_ptl_fee（费率）、dwd_ptl_managers（产品经理）、"
            "dwd_ptl_open_plan（开放计划）。"
        ),
        consistency=(
            "PORT_ID 在 dwd_ptl_info 唯一，所有子表 PORT_ID 必须命中主表（匹配率应为 100%）。"
            "持仓表 dwd_ptl_ast_hld 中 SUM(MKT_VAL) 应等于 dwd_ptl_acct_bal 的 ASSET_TOTAL ± 现金；"
            "申赎流水（_cedetail）累计净额应与 _holder_summary 的份额变动一致；"
            "费率表 _fee 与会计估值中的应付管理费/托管费勾稽（按日计提）。"
        ),
        distribution=(
            "5 个产品涵盖 MMF/BOND/MIXED/INDEX 4 种类型，规模分布中纯债二号与货币四号占主导。"
            "ptl_ast_hld 持仓集中度（前五大持仓占比）债券类约 35%~50%，指数类按基准复制接近基准权重。"
            "持有人结构中机构客户占比 60%~80%（前海资管、社保中心为大额持有人）；"
            "申赎流水呈现月度尖峰（季末/月末赎回上行）。"
        ),
        anomaly=(
            "重点排查：①持仓 MKT_VAL 与账户余额勾稽差额 > 0.5%；"
            "②单只资产持仓占比 > 10%（双十规则）的集中度违规；"
            "③单日申赎金额超过产品规模 5% 的大额异常；"
            "④负偏离（净值低于面值）的预警；"
            "⑤未授权产品经理或托管人变更；"
            "⑥开放期外现金净流出。"
        ),
        scenarios=[
            "产品组合穿透与持仓归因",
            "申赎冲击与流动性管理",
            "管理费/托管费应计核对",
            "持有人结构集中度风控",
            "双十规则合规检查",
            "现金账户与投资账户资金往来对账",
        ],
        join_keys={
            "PORT_ID": "产品全域统一关联键，跨 12 表",
            "AST_CD": "dwd_ptl_ast_hld 与资产域的桥梁",
            "BIZ_DT": "持仓/账户余额/申赎流水的快照键",
            "CUSTOMER_ID": "dwd_ptl_holder_summary 与客户域桥梁（机构持有人）",
        },
    ),

    # ============================================================
    # 4. 估值域 — 10 表，PORT_ID + BIZ_DT 双主键
    # ============================================================
    "valuation": IntraDomainProfile(
        profile_id="l2_valuation",
        domain="valuation",
        domain_name="估值域",
        tables_involved=[
            "dwd_val_valtable", "dwd_val_voucher", "dwd_val_summary",
            "dwd_val_detail", "dwd_val_notice", "dwd_val_bal",
            "dwd_val_acc", "dwd_val_rpt_bs", "dwd_val_rpt_is", "dwd_val_rpt_cf",
        ],
        structure=(
            "以 PORT_ID + BIZ_DT 形成日级估值快照。dwd_val_summary 为单行汇总（净值、份额、规模），"
            "dwd_val_detail 为按 AST_CD 展开的科目明细（1:N），dwd_val_bal 为科目余额表（试算平衡），"
            "dwd_val_voucher 为会计凭证（1:N）。dwd_val_valtable / dwd_val_acc 为估值表与科目主数据。"
            "三大报表 _rpt_bs/_is/_cf 按月度/季度生成（PORT_ID + RPT_DT 1:1）。"
            "dwd_val_notice 为净值披露公告（每日 1 条）。"
        ),
        consistency=(
            "核心勾稽：summary.NAV × summary.UNITS = detail.SUM(MKT_VAL) ± 现金科目；"
            "bal 借贷必须平衡（误差 < 0.01）；voucher 借方合计 = 贷方合计；"
            "BS 资产 = 负债 + 权益；IS 净利润应等于公允价值变动损益 + 投资收益 + 利息收入 - 费用；"
            "CF 期末现金 = 期初现金 + 经营活动 + 投资活动 + 筹资活动现金流。"
            "BIZ_DT 必须为交易日，不允许节假日断点（货币基金除外）。"
        ),
        distribution=(
            "净值（NAV）变动呈低波动平稳序列，债券类年化波动 < 3%，混合类 5%~12%；"
            "估值科目集中在债券投资、银行存款、买入返售、应付管理费等十余项；"
            "凭证笔数日均 30~80 笔，季末因费用计提与利息归本笔数显著上升 2~3 倍。"
        ),
        anomaly=(
            "重点排查：①summary 与 detail 勾稽差 > 0.1% 的估值断链；"
            "②NAV 单日变动 > 3σ 的异常波动；"
            "③试算不平衡（bal 失衡）；"
            "④凭证摘要为空或科目错配；"
            "⑤估值日期错位（晚于 BIZ_DT 后 T+1 仍未生成）；"
            "⑥三大报表勾稽失败或负债大于资产。"
        ),
        scenarios=[
            "净值勾稽与估值表自动核对",
            "三大报表自动生成与审计",
            "费用应计与冲回核对",
            "公允价值变动归因",
            "估值差异溯源（公允 vs 摊余）",
            "TA 净值发布前合规检查",
        ],
        join_keys={
            "PORT_ID": "估值全表统一外键，连接产品域",
            "BIZ_DT": "估值快照键，与产品/交易/行情对齐",
            "AST_CD": "dwd_val_detail 资产明细外键",
            "ACC_CD": "_acc 科目代码 → _bal/_voucher 关联",
            "RPT_DT": "三大报表的报告期键",
        },
    ),

    # ============================================================
    # 5. 交易域 — 6 表，ORDER_ID/TRADE_ID 为核心
    # ============================================================
    "transaction": IntraDomainProfile(
        profile_id="l2_transaction",
        domain="transaction",
        domain_name="交易域",
        tables_involved=[
            "dwd_trn_order", "dwd_trn_trade_ast", "dwd_trn_trade_ptl",
            "dwd_trn_trade_val", "dwd_trn_trade_zg", "dwd_trn_trade_jy",
        ],
        structure=(
            "dwd_trn_order 为下单指令主表（ORDER_ID 主键），可拆分为多笔成交。"
            "dwd_trn_trade_ast 为按资产视角的成交明细（TRADE_ID 主键，外键 ORDER_ID + AST_CD）；"
            "trade_ptl 为产品视角成交聚合（PORT_ID + TRADE_DT 维度）；"
            "trade_val 为估值口径成交（接入估值流水）；"
            "trade_zg 为中债登/中证登过户记录；"
            "trade_jy 为交易所托管登记记录。"
            "构成 1 单 → N 笔成交 → 多个登记/估值视图的扇出结构。"
        ),
        consistency=(
            "ORDER_ID 数量 = SUM(trade_ast.QTY)；订单状态终态（FILLED/CANCELED）应匹配成交量；"
            "trade_ast.AMT = trade_ptl.AMT_AGG（按 PORT 聚合误差 < 0.01）；"
            "中债登/中证登/交易所登记记录应与 trade_ast 1:1 匹配（按市场分流）；"
            "交易日 TRADE_DT 必须为合法交易日历内日期；CNTP_ID 必须在主体域存在。"
        ),
        distribution=(
            "交易品种分布约为债券（银行间）70% / ETF（交易所）20% / 股票 10%；"
            "下单时段集中在 09:30-11:30 与 13:00-15:00；"
            "单笔成交金额货币市场千万级、股票百万级、债券亿元级；"
            "交易对手集中在 5 家券商/银行金融市场部，CR3 约 70%。"
        ),
        anomaly=(
            "重点排查：①订单超时未成交或部分成交后久挂；"
            "②同一 ORDER_ID 下成交价偏离市场中价 > 0.3%；"
            "③TRADE_AMT 与 QTY×PRICE 不符；"
            "④成交后未在 trade_zg/trade_jy 形成登记记录的过户失败；"
            "⑤跨日反向交易（疑似洗售/对敲）；"
            "⑥未登记 CNTP 或非工作时间下单。"
        ),
        scenarios=[
            "订单全生命周期追溯",
            "成交质量分析（VWAP/TWAP偏离）",
            "异常交易行为识别",
            "成交-估值-登记三方对账",
            "对手方信用敞口监控",
            "交易费用与佣金归集",
        ],
        join_keys={
            "ORDER_ID": "下单指令主键，扇出至成交明细",
            "TRADE_ID": "成交流水主键，连接登记/估值/产品视角",
            "PORT_ID": "产品维度外键 → 产品域",
            "AST_CD": "资产维度外键 → 资产域",
            "CNTP_ID": "交易对手外键 → 主体域",
            "TRADE_DT": "交易日期，多视图对齐键",
        },
    ),

    # ============================================================
    # 6. 客户域 — 9 表（README 列 8 表，含 yh，实际 9 张），CUSTOMER_ID 核心
    # ============================================================
    "customer": IntraDomainProfile(
        profile_id="l2_customer",
        domain="customer",
        domain_name="客户域",
        tables_involved=[
            "dwd_cust_info", "dwd_cust_make_pstn_info",
            "dwd_cust_trans_acct_info", "dwd_cust_trans_apply_info_s5",
            "dwd_cust_trans_apply_info_ta", "dwd_cust_trans_apply_info_yh",
            "dwd_cust_trans_cfm_info", "dwd_cust_trans_divd_info",
            "dwd_cust_trans_srl_info",
        ],
        structure=(
            "以 dwd_cust_info（CUSTOMER_ID 主键）为客户主表（7 个客户）。"
            "持仓维度 dwd_cust_make_pstn_info（CUSTOMER_ID × PORT_ID 持仓快照 1:N）；"
            "账户维度 dwd_cust_trans_acct_info；"
            "申请维度按渠道拆分为 _s5（直销）/_ta（TA 系统）/_yh（银行代销）三表；"
            "确认维度 _cfm_info（申请→确认 1:1 回写）；"
            "分红 _divd_info；流水 _srl_info（资金流水明细）。"
        ),
        consistency=(
            "客户持仓份额 = SUM(申请确认份额) - SUM(赎回确认份额) + SUM(分红再投份额)；"
            "申请-确认匹配率应 ≥ 99%（T+1/T+2 时效内）；"
            "三渠道申请合计应等于产品域 dwd_ptl_cedetail 的总申赎；"
            "客户的 PORT_ID 必须在产品域存在；KYC 信息（风险等级 R1-R5）必须与购买产品风险等级匹配。"
        ),
        distribution=(
            "客户结构：4 个零售客户 + 3 个机构客户（前海资管、社保中心、教育基金会）；"
            "申请笔数零售客户日均 1~3 笔，机构客户呈现月末、季末集中申赎；"
            "持仓集中度机构客户单产品规模占其总持仓 60%~80%；"
            "分红再投资比例约 70%，现金分红 30%；"
            "TA 渠道占比 50%、银行代销 35%、直销 15%。"
        ),
        anomaly=(
            "重点排查：①申请未在 T+2 内确认的待结算异常；"
            "②单客户单日大额申赎 > 客户持仓 30%；"
            "③风险等级错配（R5 产品被 R1/R2 客户购买）；"
            "④账户冻结但仍发生交易；"
            "⑤分红记录与净值除权信息不一致；"
            "⑥同一身份证多客户号疑似重复开户。"
        ),
        scenarios=[
            "客户持仓与净值穿透",
            "申赎确认时效监控",
            "适当性管理与风险等级匹配",
            "客户大额异动预警",
            "分红再投资执行核对",
            "渠道营销贡献分析",
        ],
        join_keys={
            "CUSTOMER_ID": "客户全域统一主键，9 表共享",
            "PORT_ID": "持仓/申请/确认与产品域的桥梁",
            "TRANS_ID/CFM_ID": "申请与确认的关联标识",
            "BIZ_DT": "持仓与流水快照键",
        },
    ),

    # ============================================================
    # 7. 风险域 — 5 表，ISR_ID + AST_CD 双核心
    # ============================================================
    "risk": IntraDomainProfile(
        profile_id="l2_risk",
        domain="risk",
        domain_name="风险域",
        tables_involved=[
            "dwd_rsk_sentiment", "dwd_rsk_credit",
            "dwd_rsk_credit_position", "dwd_crdt_agme_info",
            "dwd_crdt_main_rela_rela_info",
        ],
        structure=(
            "dwd_rsk_credit 为内部信用评级表（按 ISR_ID 评级），_credit_position 按 PORT_ID×ISR_ID 记录信用敞口；"
            "dwd_rsk_sentiment 为舆情事件表（ISR_ID 1:N 时序事件）；"
            "dwd_crdt_agme_info 为担保协议（GUARANTOR_ISR_ID → DEBTOR_ISR_ID 双向 1:N）；"
            "dwd_crdt_main_rela_rela_info 为关联关系图（母子公司、同业、互保），形成主体间风险传染网络。"
        ),
        consistency=(
            "_credit 中 ISR_ID 必须在主体域存在；内部评级与外部评级（行情域 dwd_mkt_rating）应保持等级差 ≤ 1 档；"
            "_credit_position 敞口合计应等于产品域 dwd_ptl_ast_hld 中按发行人聚合的市值；"
            "担保链中担保人净资产应 ≥ 担保余额 × 担保系数，否则触发担保失效预警；"
            "舆情事件需带时间戳与情感分（-1~1）。"
        ),
        distribution=(
            "8 个发行人内部评级集中在 AAA-AA 级（80% 投资级），AA- 及以下属下沉敞口；"
            "舆情事件日均 0~2 条，负面占比约 25%；"
            "担保链平均深度 2 层，少数互保结构涉及 3+ 节点；"
            "信用敞口集中于政策性银行与国有大行（占敞口 60%+）。"
        ),
        anomaly=(
            "重点排查：①内部评级与外部评级背离 ≥ 2 档；"
            "②舆情情感分单日 < -0.5 的负面冲击；"
            "③担保链断裂（担保人评级下调或自身违约）；"
            "④单一发行人信用敞口超过组合净值 10%（集中度违规）；"
            "⑤互保循环导致风险净额测算失真；"
            "⑥关联关系未披露形成的隐性风险。"
        ),
        scenarios=[
            "信用评级下调预警与债券估值重定价",
            "舆情驱动的早期风险识别",
            "担保链穿透与代偿能力评估",
            "关联交易风险与利益输送识别",
            "信用集中度合规检查",
            "信用迁徙矩阵与违约率回溯",
        ],
        join_keys={
            "ISR_ID": "信用评级/敞口/舆情/担保/关联关系的核心实体键，对接主体域",
            "AST_CD": "信用敞口与具体债券资产的桥梁，对接资产域",
            "PORT_ID": "_credit_position 的产品维度键",
            "EVENT_DT": "舆情事件时间戳",
        },
    ),

    # ============================================================
    # 8. 行情域 — 25 表，AST_CD/INDEX_CD/CURVE_ID + BIZ_DT 多核心
    # ============================================================
    "market": IntraDomainProfile(
        profile_id="l2_market",
        domain="market",
        domain_name="行情域",
        tables_involved=[
            "dwd_mkt_bond", "dwd_mkt_bond_amount", "dwd_mkt_bond_creditrating",
            "dwd_mkt_bond_duration", "dwd_mkt_bond_ecl", "dwd_mkt_bond_market",
            "dwd_mkt_calendar", "dwd_mkt_date",
            "dwd_mkt_curve", "dwd_mkt_curve_quote",
            "dwd_mkt_exrate",
            "dwd_mkt_fund", "dwd_mkt_fund_allocation", "dwd_mkt_fund_derive",
            "dwd_mkt_fund_market", "dwd_mkt_fund_structure", "dwd_mkt_fund_suspension",
            "dwd_mkt_index", "dwd_mkt_index_member", "dwd_mkt_index_quote",
            "dwd_mkt_rate", "dwd_mkt_rate_quote",
            "dwd_mkt_rating", "dwd_mkt_stock", "dwd_mkt_stock_yield",
        ],
        structure=(
            "按品种分为 6 个子集群：①债券组（_bond/_amount/_creditrating/_duration/_ecl/_market）以 AST_CD+BIZ_DT 聚合行情；"
            "②基金组（_fund/_allocation/_derive/_market/_structure/_suspension）以 AST_CD+BIZ_DT；"
            "③股票组（_stock/_stock_yield）以 AST_CD+BIZ_DT；"
            "④指数组（_index/_index_member/_index_quote）以 INDEX_CD+BIZ_DT，含 1:N 成份股；"
            "⑤曲线组（_curve/_curve_quote）以 CURVE_ID+TENOR+BIZ_DT；"
            "⑥利率/汇率/评级组（_rate/_rate_quote/_exrate/_rating）。"
            "_calendar/_date 为时间维度主数据，提供交易日与节假日校验。"
        ),
        consistency=(
            "BIZ_DT 必须为 _calendar 中标识为 IS_TRADE_DAY=1 的日期；"
            "_index_member.SUM(WEIGHT) ≈ 1.0（误差 < 0.5%）；"
            "_curve_quote 沿期限结构应单调或弱递增（短端 < 长端，异常倒挂需标注）；"
            "_bond 估值价格应在 _bond_market 区间内（最高价 ≥ 收盘价 ≥ 最低价）；"
            "_rating 中外部评级映射 AAA/AA+/.../C 标准 9 档；"
            "_exrate 直接报价与间接报价乘积 ≈ 1（套利校验）。"
        ),
        distribution=(
            "债券组覆盖国债、政金债、信用债、ABS、NCD 等 5 大品种；"
            "曲线组 5 条主流曲线（CGB/CDB/AAA_MTN/AAAm_NCD/SHIBOR）期限 1D~30Y；"
            "指数组 5 大宽基指数（沪深300/中证500/创业板/上证50/中证全债）；"
            "汇率组 6 大币种 30+ 货币对；"
            "基金组覆盖 ETF、LOF、专户等。"
            "数据频率：日线为主，部分曲线/利率为日内多次更新。"
        ),
        anomaly=(
            "重点排查：①收盘价偏离 5 日均线 > 5σ 的极端波动；"
            "②曲线倒挂（10Y < 1Y）的衰退信号；"
            "③成交量连续 3 日为 0 的流动性枯竭；"
            "④指数成份股权重和偏离 1.0 ±0.5%；"
            "⑤基金净值与申报净值偏离的暂停申赎风险；"
            "⑥外部评级单档下调对应估值未跟随调整的滞后；"
            "⑦汇率交叉套利偏差（如 USDCNY × CNYHKD ≠ USDHKD）。"
        ),
        scenarios=[
            "曲线变动驱动的债券组合重定价",
            "指数复制与跟踪误差监控",
            "波动率聚类与极端行情识别",
            "汇率波动对组合估值影响测算",
            "评级迁徙触发的信用债估值调整",
            "基金停牌/复牌事件管理",
            "宏观利率与组合久期匹配",
        ],
        join_keys={
            "AST_CD": "债券/股票/基金组核心键，连接资产域",
            "INDEX_CD": "指数组主键，与 _member 关联成份股",
            "CURVE_ID": "曲线组主键，连接 _curve_quote 期限结构",
            "BIZ_DT": "全域时序快照键，需通过 _calendar 校验",
            "CCY_PAIR": "汇率组货币对键",
            "TENOR": "曲线/利率期限键",
        },
    ),
    # ============================================================
    # 9. 通用数据接入域 — 6 表，records + batches 双表结构
    # ============================================================
    "data_hub": IntraDomainProfile(
        profile_id="l2_data_hub",
        domain="data_hub",
        domain_name="通用数据接入域",
        tables_involved=[
            "subject_risk_records",
            "subject_risk_import_batches",
            "zysc_ptl_info_records",
            "zysc_ptl_info_import_batches",
            "zysc_ptl_holder_records",
            "zysc_ptl_holder_import_batches",
        ],
        structure=(
            "采用『业务记录表 + 导入批次表』双表配对结构，每类数据源对应一对："
            "subject_risk_records ←→ subject_risk_import_batches（通过 _batch_id 关联），"
            "zysc_ptl_info_records ←→ zysc_ptl_info_import_batches（通过 _batch_id 关联），"
            "zysc_ptl_holder_records ←→ zysc_ptl_holder_import_batches（通过 _batch_id 关联）。"
            "\n\n三组表之间通过『产品代码』形成逻辑关联：zysc_ptl_info_records.产品代码 "
            "= zysc_ptl_holder_records.产品代码；主体风险表通过 subject_name "
            "与产品域的管理人/发行人形成语义关联。"
        ),
        consistency=(
            "每张 records 表的 _batch_id 必须在对应 batches 表中存在（实际检测：subject_risk有1个孤儿批次，"
            "zysc_ptl_info有1个孤儿批次，zysc_ptl_holder完全匹配）；"
            "zysc_ptl_holder_records.产品代码 100%命中 zysc_ptl_info_records.产品代码（35个产品×5期=175条）；"
            "subject_risk_records.subject_name 覆盖18个独立主体，与 dwd_isr_institution.ISR_NM 语义匹配；"
            "前十份额与个人份额+机构份额为独立统计口径（非加和关系），前十为Top10持有人合计，个人+机构为投资者类型合计；"
            "batches 表的 inserted + updated + failed 总和应等于 total_returned。"
        ),
        distribution=(
            "subject_risk_records(40条) 风险等级分布：黄色50%(20条)、高30%(12条)、低20%(8条)，"
            "高风险集中于万科/碧桂园/恒大三家房地产企业；企业性质：国有53%(21条)、民营35%(14条)、混合所有制12%(5条)；"
            "rule_large分布：客户经营情况(14)、客户财务情况(9)、客户融资情况(6)、客户信用情况(4)、客户舆情情况(4)；"
            "zysc_ptl_info_records(35条) 全部为理财产品（100%），风险等级 R3(63%)>R4(17%)>R2(14%)>R1(6%)；"
            "估值方法以市值法为主(91%,32条)，摊余成本法(9%,3条)；策略类型FOF配置(9)>CTA趋势(8)>混合策略(5)；"
            "35个产品代码与产品域 dwd_ptl_info 100%匹配；"
            "zysc_ptl_holder_records(175条) 五期数据(2025-06-30×35、2025-12-31×35、2026-03-31×35、2026-06-30×35、2026-09-30×35)；"
            "前十份额范围6572万-37.36亿，均值14.73亿；机构份额均值15.39亿，个人份额均值11.46亿；"
            "跨期机构占比漂移平均±0.7%，最大±25%（R4高风险产品漂移更大，R1/R2更稳定）；"
            "batches表(12条) status分布：success(7)、partial(3)、failed_upstream(2)。"
        ),
        anomaly=(
            "重点排查：①_batch_id 孤儿记录（实际发现：subject_risk和zysc_ptl_info各1个孤儿批次，"
            "即records中的_batch_id在batches表中不存在，可能为批次记录被清理或导入异常）；"
            "②batches表中存在failed_upstream状态(2条)，表明上游接口曾返回错误，需关注数据完整性；"
            "③产品信息表中到期日早于起息日（上游数据错误）；"
            "④风险记录中同一主体24h内触发多条高风险信号（万科/碧桂园/恒大多条高风险聚集）；"
            "⑤持有人数据五期间隔6个月/3个月，支持季度级持有人结构变迁分析；"
            "⑥zysc_ptl_info的partial批次表明上游pageMsg限制导致数据截断。"
        ),
        scenarios=[
            "数据导入质量审计与批次溯源（含failed_upstream根因分析）",
            "产品持有人结构变迁分析（五期机构/个人占比变化趋势，支持季度级对比）",
            "风险主体与持仓产品的交叉监控（18个主体→产品管理人关联）",
            "上游接口健康度监控（success/partial/failed_upstream趋势）",
            "批次孤儿记录检测与数据完整性核查",
            "产品全生命周期数据完整性核查（起息日→到期日）",
        ],
        join_keys={
            "_batch_id": "records → batches 的溯源键，每次导入生成唯一批次",
            "产品代码": "产品信息表与持有人表的逻辑主键",
            "subject_name": "风险主体名称，与主体域 ISR_NM 语义关联",
            "risk_id": "风险事件唯一标识",
        },
    ),
}

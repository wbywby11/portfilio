"""
通用数据接入域（data_hub）真实化数据生成脚本

生成 3 张业务表 + 3 张批次表的真实字段数据，确保与 9 域 82 表的高关联性：
- subject_risk_records.subject_name ↔ dwd_isr_institution.ISR_NM
- zysc_ptl_info_records.产品代码 ↔ dwd_ptl_info.PORT_ID
- zysc_ptl_holder_records.产品代码 ↔ zysc_ptl_info_records.产品代码

用法：
  python scripts/generate_datahub_realistic_data.py             # 执行（替换模式）
  python scripts/generate_datahub_realistic_data.py --dry-run   # 仅预览
"""
import random
import sys
import uuid
from datetime import datetime, timedelta

random.seed(42)  # 可复现


def main():
    dry_run = "--dry-run" in sys.argv
    from pymongo import MongoClient
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]

    now_iso = datetime.now().isoformat()

    # ================================================================
    #  1. subject_risk_records — 主体观点风险记录（40 条）
    # ================================================================
    # 高关联：使用 dwd_isr_institution 中的真实主体名称
    REAL_SUBJECTS = [
        # (主体名称, 主体类型, 行业, 省份, 企业性质, 统一社会信用代码)
        ("万科企业股份有限公司", "企业法人(非金融机构)", "房地产业-房地产开发经营", "广东省", "混合所有制", "91440300717802677D"),
        ("碧桂园控股有限公司", "企业法人(非金融机构)", "房地产业-房地产开发经营", "广东省", "民营企业", "91440606063326711X"),
        ("中国恒大集团", "企业法人(非金融机构)", "房地产业-房地产开发经营", "广东省", "民营企业", "91440300715354046X"),
        ("绿地控股集团有限公司", "企业法人(非金融机构)", "房地产业-房地产开发经营", "上海市", "国有企业", "913100001322214479"),
        ("保利发展控股集团股份有限公司", "企业法人(非金融机构)", "房地产业-房地产开发经营", "广东省", "国有企业", "914401017178330439"),
        ("中国工商银行股份有限公司", "企业法人(金融机构)", "金融业-货币金融服务", "北京市", "国有企业", "91110000100003962T"),
        ("中国建设银行股份有限公司", "企业法人(金融机构)", "金融业-货币金融服务", "北京市", "国有企业", "91110000100002972X"),
        ("招商银行股份有限公司", "企业法人(金融机构)", "金融业-货币金融服务", "广东省", "国有企业", "91440300100016804A"),
        ("中信证券股份有限公司", "企业法人(金融机构)", "金融业-资本市场服务", "广东省", "国有企业", "91440300101710393P"),
        ("华泰证券股份有限公司", "企业法人(金融机构)", "金融业-资本市场服务", "江苏省", "国有企业", "91320000704041466G"),
        ("中国平安保险(集团)股份有限公司", "企业法人(金融机构)", "金融业-保险业", "广东省", "混合所有制", "91440300100006488L"),
        ("华为投资控股有限公司", "企业法人(非金融机构)", "信息传输、软件和信息技术服务业", "广东省", "民营企业", "91440300715256993W"),
        ("腾讯控股有限公司", "企业法人(非金融机构)", "信息传输、软件和信息技术服务业", "广东省", "民营企业", "91440300708461136T"),
        ("比亚迪股份有限公司", "企业法人(非金融机构)", "制造业-汽车制造业", "广东省", "民营企业", "91440300192317458F"),
        ("中国铁道建筑集团有限公司", "企业法人(非金融机构)", "建筑业-土木工程建筑业", "北京市", "国有企业", "91110000100002288L"),
        ("中国交通建设股份有限公司", "企业法人(非金融机构)", "建筑业-土木工程建筑业", "北京市", "国有企业", "91110000710934361L"),
        ("中国中铁股份有限公司", "企业法人(非金融机构)", "建筑业-土木工程建筑业", "北京市", "国有企业", "911100007109351850"),
        ("阿里巴巴集团控股有限公司", "企业法人(非金融机构)", "信息传输、软件和信息技术服务业", "浙江省", "民营企业", "913301007999990359"),
    ]

    # 风险等级分布：高 20%, 黄 55%, 低 25%
    RISK_LEVELS = ["高"] * 8 + ["黄"] * 22 + ["低"] * 10

    # 规则体系
    RULE_LARGE_POOL = [
        "客户经营情况", "客户融资情况", "客户信用情况",
        "客户合规情况", "客户舆情情况", "客户财务情况",
    ]
    RULE_MEDIUM_POOL = [
        "司法及行政处罚事件", "人行征信预警", "债务违约事件",
        "重大经营异常", "高管变动事件", "股权冻结/质押",
        "信用评级调整", "重大诉讼仲裁", "负面舆情传播",
        "财务报表异常", "关联交易异常", "监管处罚事件",
    ]
    RULE_SMALL_POOL = [
        "企业涉及及大额被执行案件（法院）",
        "企业近期贷款余额波动较大(二代征信)",
        "企业出现债务逾期或展期（公开市场）",
        "企业主体评级被下调或展望调为负面",
        "企业高管被立案调查或限制高消费",
        "企业股权被司法冻结超过5%注册资本",
        "企业涉及重大诉讼且标的额超过净资产10%",
        "企业连续两期财报营收下降超过20%",
        "企业关联方出现债务违约事件",
        "企业被监管部门出具警示函或行政处罚",
        "企业主体被列入失信被执行人名单",
        "企业债券出现利息支付延迟",
        "企业银行授信额度大幅缩减",
        "企业核心资产被查封或扣押",
        "企业实控人或法人被限制出境",
    ]

    # 信号描述模板
    SIGNAL_TEMPLATES = [
        "企业（{name}）（{date}）涉及大额被执行案件，案号（(2025){court}执{case_no}号），执行金额（{amount}万元）。相关情况需结合司法文书与偿债能力综合评估舆情与合规影响。",
        "企业({name})本期({date})征信报告反映贷款余额为({balance}万元)，较上期({prev_date})的贷款余额减少{pct}%以上。",
        "企业({name})({date})主体信用评级由{old_rating}下调至{new_rating}，展望调整为负面。评级机构关注其{reason}。",
        "企业({name})({date})公告其高级管理人员{exec_name}因涉嫌{reason2}被立案调查，目前公司生产经营暂未受重大影响，但后续存在不确定性。",
        "企业({name})({date})涉及重大诉讼案件，原告为{plaintiff}，诉讼标的金额{amount2}亿元，案件处于{stage}阶段。",
        "企业({name})({date})出现银行授信额度缩减，授信总额由{orig_credit}亿元降至{new_credit}亿元，缩减比例约{shrink}%，流动性压力上升。",
        "企业({name})({date})发生债务展期事件，涉及{bond_name}利息支付约{int_amt}万元，展期期限{ext_days}天。市场对其偿债能力关注度上升。",
        "企业({name})({date})股权被司法冻结，冻结股份占总股本{freeze_pct}%，冻结期限至{freeze_end}，涉及{court2}法院执行案件。",
    ]

    risk_docs = []
    for i, risk_level in enumerate(RISK_LEVELS):
        subj = REAL_SUBJECTS[i % len(REAL_SUBJECTS)]
        name, stype, industry, province, nature, uscc = subj

        # 业务日期分散在 2025-07 至 2026-05
        biz_date = (datetime(2025, 7, 1) + timedelta(days=random.randint(0, 320))).strftime("%Y-%m-%d")
        data_date = "2026-05-26"
        sign_date = (datetime.strptime(biz_date, "%Y-%m-%d") - timedelta(days=random.randint(1, 15))).strftime("%Y-%m-%d")

        rule_l = random.choice(RULE_LARGE_POOL)
        rule_m = random.choice(RULE_MEDIUM_POOL)
        rule_s = random.choice(RULE_SMALL_POOL)

        # 高风险主体关联房地产企业（万科/碧桂园/恒大/绿地）
        if name in ("万科企业股份有限公司", "碧桂园控股有限公司", "中国恒大集团"):
            risk_level = "高"
            rule_l = "客户经营情况"
            rule_m = random.choice(["司法及行政处罚事件", "债务违约事件", "重大经营异常"])
        elif name in ("绿地控股集团有限公司",):
            risk_level = random.choice(["高", "黄"])
        elif nature == "国有企业" and "银行" not in name and "证券" not in name:
            risk_level = random.choice(["黄", "低"])

        # 生成信号描述
        tmpl = random.choice(SIGNAL_TEMPLATES)
        signal = tmpl.format(
            name=name, date=biz_date, court="京0108", case_no=random.randint(10000, 99999),
            amount=round(random.uniform(100, 5000), 2),
            balance=round(random.uniform(50000, 500000), 2),
            prev_date=(datetime.strptime(biz_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d"),
            pct=random.choice([30, 35, 40, 50]),
            old_rating=random.choice(["AA+", "AA", "AA-"]),
            new_rating=random.choice(["AA-", "A+", "A"]),
            reason=random.choice(["债务集中到期压力", "经营现金流恶化", "或有负债风险上升"]),
            exec_name=random.choice(["张某", "李某", "王某"]),
            reason2=random.choice(["职务侵占", "信息披露违规", "内幕交易"]),
            plaintiff=random.choice(["某商业银行", "某信托公司", "某资产管理公司"]),
            amount2=round(random.uniform(1, 50), 2),
            stage=random.choice(["一审", "二审", "执行"]),
            orig_credit=round(random.uniform(100, 500), 0),
            new_credit=round(random.uniform(50, 200), 0),
            shrink=random.randint(30, 60),
            bond_name=f"{name[:4]}2024年公司债",
            int_amt=round(random.uniform(500, 5000), 0),
            ext_days=random.choice([30, 60, 90]),
            freeze_pct=round(random.uniform(5, 25), 1),
            freeze_end="2026-12-31",
            court2=random.choice(["北京市第一中级人民法院", "深圳市中级人民法院", "广州市中级人民法院"]),
        )

        # 白名单标识
        is_approved = "是" if nature == "国有企业" and "银行" in name else "否"
        is_partner = "是" if nature == "国有企业" and random.random() > 0.6 else "否"
        is_veto = "是" if name in ("中国恒大集团",) else "否"

        risk_id = f"{biz_date.replace('-','')[:8]}DG{random.randint(100000,999999)}{random.randint(10000000,99999999)}"

        doc = {
            "risk_id": risk_id,
            "biz_date": biz_date,
            "data_date": data_date,
            "sign_date": sign_date,
            "subject_name": name,
            "subject_type": stype,
            "unified_social_credit_code": uscc if random.random() > 0.15 else None,
            "enterprise_nature": nature,
            "industry_classification_gb": industry,
            "risk_signal_level": risk_level,
            "signal_dascribe": signal,
            "rule_large": rule_l,
            "rule_medium": rule_m,
            "rule_small": rule_s,
            "affiliated_province": province,
            "affiliated_city": random.choice(["深圳市", "广州市", "北京市", "上海市", "杭州市", "南京市", None]),
            "affiliated_county_town": None,
            "is_approved_investment_quota_client": is_approved,
            "is_partner_access_client": is_partner,
            "is_parent_bank_veto_client": is_veto,
            "parent_bank_classify_queue_type": random.choice(["增进类客户", "维持类客户", "压缩类客户", None]),
            "parent_bank_monitor_manager_type": random.choice(["无", "重点关注", "一般关注"]),
            "wealth_child_monitor_manager_type": random.choice([None, None, "一般关注"]),
            "financial_lease_monitor_manager_type": None,
            "_batch_id": f"batch_risk_{(i // 10) + 1:02d}",
            "_imported_at": now_iso,
        }
        risk_docs.append(doc)

    # ================================================================
    #  2. zysc_ptl_info_records — 产品信息记录（35 条）
    # ================================================================
    # 高关联：桥接 dwd_ptl_info 中的产品
    PRODUCT_BRIDGES = [
        ("PTL_001", "稳健收益1号", "ZS-PTL-001", "浙银理财稳泰2024年第1期", "理财产品", "010", "稳健", "R2", "浙银理财", "市值法"),
        ("PTL_002", "稳健收益2号", "ZS-PTL-002", "浙银理财璟衡涌盈添利安享151号", "理财产品", "010", "稳健", "R2", "浙银理财", "市值法"),
        ("PTL_003", "稳健收益3号", "ZS-PTL-003", "浙银理财珠衡宝石涌盈添利178号", "理财产品", "010", "稳健", "R2", "浙银理财", "摊余成本法"),
        ("PTL_004", "进取成长1号", "ZS-PTL-004", "浙银理财成长优选混合策略1号", "理财产品", "020", "进取", "R3", "浙银理财", "市值法"),
        ("PTL_005", "进取成长2号", "ZS-PTL-005", "浙银理财科技创新成长2号", "理财产品", "020", "进取", "R3", "浙银理财", "市值法"),
        ("PTL_006", "平衡配置1号", "ZS-PTL-006", "浙银理财平衡精选配置1号", "理财产品", "030", "平衡", "R3", "浙银理财", "市值法"),
        ("PTL_007", "平衡配置2号", "ZS-PTL-007", "浙银理财股债平衡2号", "理财产品", "030", "平衡", "R3", "浙银理财", "市值法"),
        ("PTL_008", "货币市场1号", "ZS-PTL-008", "浙银理财日日金货币1号", "理财产品", "040", "货币", "R1", "浙银理财", "摊余成本法"),
        ("PTL_009", "货币市场2号", "ZS-PTL-009", "浙银理财天天利货币2号", "理财产品", "040", "货币", "R1", "浙银理财", "摊余成本法"),
        ("PTL_010", "FOF精选1号", "ZS-PTL-010", "浙银理财FOF优选配置1号", "理财产品", "050", "FOF", "R3", "浙银理财", "市值法"),
        ("PTL_013", "港股通1号", "ZS-PTL-013", "浙银理财港股精选通1号", "理财产品", "060", "港股", "R4", "浙银理财", "市值法"),
        ("PTL_015", "新能源主题1号", "ZS-PTL-015", "浙银理财新能源产业优选1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_017", "医疗健康1号", "ZS-PTL-017", "浙银理财医疗健康精选1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_020", "量化对冲1号", "ZS-PTL-020", "浙银理财量化对冲绝对收益1号", "理财产品", "080", "量化", "R3", "浙银理财", "市值法"),
        ("PTL_025", "新能源主题1号B", "ZS-PTL-025", "浙银理财新能源2号B类", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_030", "医药健康2号", "ZS-PTL-030", "浙银理财医药健康2号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_035", "中证500增强1号", "ZS-PTL-035", "浙银理财中证500指增1号", "理财产品", "090", "指数增强", "R3", "浙银理财", "市值法"),
        ("PTL_036", "沪深300增强1号", "ZS-PTL-036", "浙银理财沪深300指增1号", "理财产品", "090", "指数增强", "R3", "浙银理财", "市值法"),
        ("PTL_040", "市场中性1号", "ZS-PTL-040", "浙银理财市场中性和谐1号", "理财产品", "080", "量化", "R2", "浙银理财", "市值法"),
        ("PTL_042", "全天候配置1号", "ZS-PTL-042", "浙银理财全天候多元配置1号", "理财产品", "030", "平衡", "R3", "浙银理财", "市值法"),
        ("PTL_046", "FOF稳健1号", "ZS-PTL-046", "浙银理财FOF稳健配置1号", "理财产品", "050", "FOF", "R2", "浙银理财", "市值法"),
        ("PTL_047", "FOF进取1号", "ZS-PTL-047", "浙银理财FOF进取配置1号", "理财产品", "050", "FOF", "R4", "浙银理财", "市值法"),
        ("PTL_049", "QDII全球精选1号", "ZS-PTL-049", "浙银理财QDII全球精选1号", "理财产品", "100", "QDII", "R4", "浙银理财", "市值法"),
        ("PTL_050", "QDII美股精选1号", "ZS-PTL-050", "浙银理财QDII美股精选1号", "理财产品", "100", "QDII", "R4", "浙银理财", "市值法"),
        ("PTL_011", "CTA趋势1号", "ZS-PTL-011", "浙银理财CTA趋势追踪1号", "理财产品", "110", "CTA", "R4", "浙银理财", "市值法"),
        ("PTL_012", "指数增强1号", "ZS-PTL-012", "浙银理财创业板指增1号", "理财产品", "090", "指数增强", "R3", "浙银理财", "市值法"),
        ("PTL_014", "科创主题1号", "ZS-PTL-014", "浙银理财科创板精选1号", "理财产品", "070", "主题", "R4", "浙银理财", "市值法"),
        ("PTL_016", "消费升级1号", "ZS-PTL-016", "浙银理财消费升级优选1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_018", "智能制造1号", "ZS-PTL-018", "浙银理财智能制造主题1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_019", "ESG责任投资1号", "ZS-PTL-019", "浙银理财ESG绿色责任1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_033", "高股息策略1号", "ZS-PTL-033", "浙银理财高股息红利策略1号", "理财产品", "080", "量化", "R3", "浙银理财", "市值法"),
        ("PTL_031", "金融地产1号", "ZS-PTL-031", "浙银理财金融地产优选1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_029", "医药健康1号", "ZS-PTL-029", "浙银理财医药健康精选1号A", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_027", "消费精选1号", "ZS-PTL-027", "浙银理财消费精选1号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
        ("PTL_022", "ESG责任投资2号", "ZS-PTL-022", "浙银理财ESG绿色责任2号", "理财产品", "070", "主题", "R3", "浙银理财", "市值法"),
    ]

    MANAGERS = ["张明远", "李慧芳", "王建国", "陈志华", "刘思远", "赵敏", "周浩然", "吴婷婷", "孙伟", "杨晓峰"]
    TRUSTEES = ["中国工商银行", "中国建设银行", "招商银行", "中国银行", "交通银行"]
    STRATEGIES = ["固收+", "混合策略", "纯债策略", "量化对冲", "指数增强", "FOF配置", "CTA趋势", "QDII海外"]
    BENCHMARKS_MKT = ["中债综合指数", "沪深300指数", "中证500指数", "中证全债指数", "中债国债总指数"]
    OPEN_FREQS = ["每日", "每周", "每月", "每季度", "每半年", "每年", "封闭"]

    ptl_info_docs = []
    for idx, (port_id, short, ext_code, full_name, nature, ptype, series_detail, risk, mgr, val_method) in enumerate(PRODUCT_BRIDGES):
        start_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 365))
        end_date = start_date + timedelta(days=random.choice([180, 270, 365, 540, 730]))
        doc = {
            "产品代码": port_id,
            "产品简称": short,
            "产品名称": full_name,
            "拉链开始日": "2025-01-01",
            "拉链结束日": "2026-05-26",
            "币种": "人民币",
            "估值方法": val_method,
            "产品性质": nature,
            "产品类型": ptype,
            "产品模式": "普通产品",
            "所属部门": random.choice(["资产管理部", "理财事业部", "私人银行部"]),
            "所属子部门": random.choice(["固定收益组", "权益投资组", "量化投资组", "FOF投资组"]),
            "管理人": mgr,
            "托管人": random.choice(TRUSTEES),
            "投资经理": random.choice(MANAGERS),
            "募集方式": random.choice(["公募", "私募", "定向"]),
            "风险等级": risk,
            "收益类型": random.choice(["非保本浮动", "保本浮动", "固定收益"]),
            "客户类型": random.choice(["个人", "机构", "个人及机构"]),
            "产品系列": random.choice(["璟衡", "珠衡", "涌盈", "稳泰", "优选"]),
            "产品系列细分": series_detail,
            "是否现金管理类": "是" if ptype == "040" else "否",
            "清盘日": end_date.strftime("%Y-%m-%d"),
            "数据日期": "2026-05-26",
            "数据时间": "08:00:00",
            "数据来源": "ZYSC",
            "导入方法": "API",
            "客户周期(天)": random.choice([0, 7, 30, 90]),
            "最短持有期限(天)": random.choice([0, 30, 90, 180]),
            "SPV分类": None,
            "建仓完成期": (start_date + timedelta(days=30)).strftime("%Y-%m-%d"),
            "募集开始日": (start_date - timedelta(days=7)).strftime("%Y-%m-%d"),
            "建仓期": 30,
            "开放类型": random.choice(["定期开放", "每日开放", "封闭运作"]),
            "开放频率": random.choice(OPEN_FREQS),
            "运行方式": "正常",
            "市场基准": random.choice(BENCHMARKS_MKT),
            "合约基准": f"{port_id}_HYJZ",
            "合约基准_上限": str(round(random.uniform(0.02, 0.06), 4)),
            "合约基准_下限": str(round(random.uniform(0.015, 0.04), 4)),
            "合约基准_平均": str(round(random.uniform(0.02, 0.05), 4)),
            "内部基准": None,
            "市场基准说明": f"对标{random.choice(BENCHMARKS_MKT)}",
            "合约基准说明": "按合同约定的基准收益率",
            "内部基准说明": None,
            "产品起息日": start_date.strftime("%Y-%m-%d"),
            "产品到期日": end_date.strftime("%Y-%m-%d"),
            "交易日历": "中国银行间交易日历",
            "策略类型": random.choice(STRATEGIES),
            "所属产品": None,
            "委外资产ID": None,
            "资管计划管理方式": "主动管理",
            "是否最短持有期": "是" if random.random() > 0.5 else "否",
            "起点销售金额/认购起点": random.choice([10000, 50000, 100000, 300000]),
            "_batch_id": f"batch_ptl_{(idx // 12) + 1:02d}",
            "_imported_at": now_iso,
            "_created_at": now_iso,
        }
        ptl_info_docs.append(doc)

    # ================================================================
    #  3. zysc_ptl_holder_records — 产品持有人汇总（70 条，35产品×2期）
    # ================================================================
    holder_docs = []
    periods = [("2025-06-30", "2025-06-30"), ("2025-12-31", "2025-12-31")]
    for period_idx, (eff_date, data_date) in enumerate(periods):
        for doc_info in ptl_info_docs:
            port_code = doc_info["产品代码"]
            risk = doc_info["风险等级"]

            # 根据风险等级设定机构/个人比例
            if risk in ("R1", "R2"):
                inst_ratio = round(random.uniform(0.3, 0.6), 4)  # 稳健型个人占多
            elif risk == "R3":
                inst_ratio = round(random.uniform(0.4, 0.7), 4)  # 平衡型机构略多
            else:
                inst_ratio = round(random.uniform(0.6, 0.9), 4)  # 进取型机构占多

            # 第二期相对第一期有小幅变动
            drift = random.uniform(-0.05, 0.05) if period_idx == 1 else 0
            inst_ratio_p2 = max(0.1, min(0.95, inst_ratio + drift))
            actual_ratio = inst_ratio_p2 if period_idx == 1 else inst_ratio
            personal_ratio = round(1 - actual_ratio, 4)

            total_shr = round(random.uniform(1e8, 5e9), 2)
            total_amt = round(total_shr * random.uniform(0.98, 1.05), 2)

            top10_ratio = round(random.uniform(0.25, 0.85), 4)
            top10_shr = round(total_shr * top10_ratio, 2)
            top10_amt = round(total_amt * top10_ratio, 2)
            inst_shr = round(total_shr * actual_ratio, 2)
            inst_amt = round(total_amt * actual_ratio, 2)
            personal_shr = round(total_shr * personal_ratio, 2)
            personal_amt = round(total_amt * personal_ratio, 2)

            holder_row_uid = f"{port_code}|{eff_date}"
            doc = {
                "_holder_row_uid": holder_row_uid,
                "产品代码": port_code,
                "生效日期": eff_date,
                "前十份额": top10_shr,
                "前十金额": top10_amt,
                "个人份额": personal_shr,
                "个人金额": personal_amt,
                "机构份额": inst_shr,
                "机构金额": inst_amt,
                "数据日期": data_date,
                "数据时间": "00:00:00",
                "数据来源": "ZYSC",
                "导入方法": "API",
                "_batch_id": f"batch_holder_{period_idx + 1:02d}",
                "_imported_at": now_iso,
                "_created_at": now_iso,
            }
            holder_docs.append(doc)

    # ================================================================
    #  4. 导入批次表（各 3 批次）
    # ================================================================
    def make_batch_docs(prefix, n=3):
        batches = []
        for i in range(n):
            started = datetime(2026, 4, 1) + timedelta(days=i * 15, hours=random.randint(8, 17))
            dur = random.randint(800, 4500)
            finished = started + timedelta(milliseconds=dur)
            total_ret = random.choice([40, 35, 70, 10])
            batches.append({
                "batch_id": f"batch_{prefix}_{i + 1:02d}",
                "status": "success" if i < n - 1 else random.choice(["success", "partial"]),
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": dur,
                "params": {"startDate": "2025-07-01", "endDate": "2026-05-26", "rownum": 100000},
                "upstream_url": "http://zylcorms.wmverify.com:8080/jxdatamid/apiManage/getPyResult",
                "upstream_code": "200",
                "upstream_message": "OK",
                "msg_list": [],
                "ind_name_list": [],
                "total_returned": total_ret,
                "inserted": total_ret - random.randint(0, 2),
                "updated": random.randint(0, 5),
                "skipped_no_key": 0,
                "failed": 0,
                "error": None,
                "sample_errors": [],
            })
        return batches

    risk_batches = make_batch_docs("risk", 3)
    ptl_batches = make_batch_docs("ptl", 2)
    holder_batches = make_batch_docs("holder", 2)

    # ================================================================
    #  执行写入
    # ================================================================
    collections = {
        "subject_risk_records": risk_docs,
        "zysc_ptl_info_records": ptl_info_docs,
        "zysc_ptl_holder_records": holder_docs,
        "subject_risk_import_batches": risk_batches,
        "zysc_ptl_info_import_batches": ptl_batches,
        "zysc_ptl_holder_import_batches": holder_batches,
    }

    if dry_run:
        for col, docs in collections.items():
            print(f"[DRY-RUN] {col}: {len(docs)} 条")
        # 打印风险分布
        from collections import Counter
        levels = Counter(d["risk_signal_level"] for d in risk_docs)
        print(f"  风险等级分布: {dict(levels)}")
        natures = Counter(d["enterprise_nature"] for d in risk_docs)
        print(f"  企业性质分布: {dict(natures)}")
        provs = Counter(d["affiliated_province"] for d in risk_docs)
        print(f"  省份分布: {dict(provs)}")
        # 打印产品分布
        risks_ptl = Counter(d["风险等级"] for d in ptl_info_docs)
        print(f"  产品风险等级: {dict(risks_ptl)}")
        vals = Counter(d["估值方法"] for d in ptl_info_docs)
        print(f"  估值方法: {dict(vals)}")
        # 打印持有人统计
        inst_ratios = [round(d["机构份额"] / (d["机构份额"] + d["个人份额"]), 2) for d in holder_docs if (d["机构份额"] + d["个人份额"]) > 0]
        print(f"  持有人机构占比: min={min(inst_ratios)}, max={max(inst_ratios)}, avg={sum(inst_ratios)/len(inst_ratios):.2f}")
        client.close()
        return

    for col, docs in collections.items():
        db[col].delete_many({})
        if docs:
            db[col].insert_many(docs)
        print(f"✓ {col}: {len(docs)} 条")

    print("\n数据生成完成！")
    client.close()


if __name__ == "__main__":
    main()

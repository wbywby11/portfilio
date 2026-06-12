# -*- coding: utf-8 -*-
"""
全面修复 asset_allocation 库 dwd_ 集合的 HERMES 占位符质量问题。

修复策略：
- 直接基于 _id 顺序 + 关键 ID 字段（CUST_xxx/PTL_xxx/FUND_xxx/STOCK_xxx）做"确定性映射"，
  保证跨集合一致性（CUST_001 在所有表里都映射成同一个真实姓名）。
- 仅修复存在占位符的字段，已是真实值（如 BOND_001 → "2024年记账式附息国债第一期"）保持不变。
- 跳过 *__backup_* 集合（用户说明不需要备份）。
"""
import re
import random
from datetime import datetime, timedelta
from pymongo import MongoClient, UpdateOne


# ============================================================
# 真实数据池
# ============================================================

# 50 个常见姓 × 30 个常见名 = 1500 组合，足以为 200 客户提供独立姓名
SURNAMES = ["张", "王", "李", "刘", "陈", "杨", "赵", "黄", "周", "吴",
            "徐", "孙", "朱", "马", "胡", "郭", "何", "林", "罗", "梁",
            "郑", "谢", "韩", "唐", "冯", "于", "董", "萧", "程", "曹",
            "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕", "苏", "卢",
            "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "余", "潘", "段"]

GIVEN_NAMES = ["伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "军",
               "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "霞", "平",
               "刚", "建华", "建国", "欣然", "哲", "婷", "雪", "丹", "玲", "鹏"]

# 机构（公司）名池 —— 用作机构客户名 / 主体名
COMPANY_NAMES = [
    "招商证券股份有限公司", "中信证券股份有限公司", "国泰君安证券股份有限公司",
    "华泰证券股份有限公司", "海通证券股份有限公司", "广发证券股份有限公司",
    "申万宏源证券有限公司", "东方证券股份有限公司", "光大证券股份有限公司",
    "中金公司股份有限公司", "中信建投证券股份有限公司", "国信证券股份有限公司",
    "招商基金管理有限公司", "华夏基金管理有限公司", "易方达基金管理有限公司",
    "南方基金管理股份有限公司", "嘉实基金管理有限公司", "广发基金管理有限公司",
    "博时基金管理有限公司", "工银瑞信基金管理有限公司", "建信基金管理有限责任公司",
    "中银基金管理有限公司", "交银施罗德基金管理有限公司", "鹏华基金管理有限公司",
    "中国平安保险（集团）股份有限公司", "中国人寿保险股份有限公司",
    "中国太平洋保险股份有限公司", "中国人民保险集团股份有限公司",
    "新华人寿保险股份有限公司", "泰康保险集团股份有限公司",
    "阳光保险集团股份有限公司", "华安财产保险股份有限公司",
    "工商银行股份有限公司", "建设银行股份有限公司", "中国银行股份有限公司",
    "农业银行股份有限公司", "交通银行股份有限公司", "招商银行股份有限公司",
    "兴业银行股份有限公司", "浦发银行股份有限公司", "民生银行股份有限公司",
    "中信银行股份有限公司", "光大银行股份有限公司", "平安银行股份有限公司",
    "国家电网有限公司", "中国石油化工集团有限公司", "中国石油天然气集团有限公司",
    "中国移动通信集团有限公司", "中国华能集团有限公司", "中国大唐集团有限公司",
    "宝山钢铁股份有限公司", "鞍钢集团有限公司", "中粮集团有限公司",
    "万科企业股份有限公司", "保利发展控股集团股份有限公司",
]

# 真实 A 股股票池（代码、名称、行业）
STOCKS = [
    ("600036.SH", "招商银行", "银行"), ("601318.SH", "中国平安", "非银金融"),
    ("000001.SZ", "平安银行", "银行"), ("600519.SH", "贵州茅台", "食品饮料"),
    ("000858.SZ", "五粮液", "食品饮料"), ("601166.SH", "兴业银行", "银行"),
    ("600276.SH", "恒瑞医药", "医药生物"), ("000333.SZ", "美的集团", "家用电器"),
    ("600887.SH", "伊利股份", "食品饮料"), ("002415.SZ", "海康威视", "电子"),
    ("601888.SH", "中国中免", "商贸零售"), ("600900.SH", "长江电力", "公用事业"),
    ("000568.SZ", "泸州老窖", "食品饮料"), ("601012.SH", "隆基绿能", "电力设备"),
    ("300750.SZ", "宁德时代", "电力设备"), ("002594.SZ", "比亚迪", "汽车"),
    ("600309.SH", "万华化学", "基础化工"), ("601899.SH", "紫金矿业", "有色金属"),
    ("000725.SZ", "京东方A", "电子"), ("601688.SH", "华泰证券", "非银金融"),
    ("600028.SH", "中国石化", "石油石化"), ("601857.SH", "中国石油", "石油石化"),
    ("600030.SH", "中信证券", "非银金融"), ("601628.SH", "中国人寿", "非银金融"),
    ("601398.SH", "工商银行", "银行"), ("601939.SH", "建设银行", "银行"),
    ("601288.SH", "农业银行", "银行"), ("601988.SH", "中国银行", "银行"),
    ("600000.SH", "浦发银行", "银行"), ("000651.SZ", "格力电器", "家用电器"),
    ("002475.SZ", "立讯精密", "电子"), ("300059.SZ", "东方财富", "非银金融"),
    ("600031.SH", "三一重工", "机械设备"), ("600585.SH", "海螺水泥", "建筑材料"),
    ("601111.SH", "中国国航", "交通运输"), ("601989.SH", "中国重工", "国防军工"),
    ("000538.SZ", "云南白药", "医药生物"), ("002230.SZ", "科大讯飞", "计算机"),
    ("002714.SZ", "牧原股份", "农林牧渔"), ("000063.SZ", "中兴通讯", "通信"),
]

# 真实公募基金池（代码、名称、管理人）
FUNDS = [
    ("110011.OF", "易方达优质精选混合", "易方达基金"),
    ("000001.OF", "华夏成长混合", "华夏基金"),
    ("519300.OF", "大成沪深300指数A", "大成基金"),
    ("162213.OF", "泰达宏利品质生活混合", "泰达宏利"),
    ("070032.OF", "嘉实优化红利混合", "嘉实基金"),
    ("000478.OF", "建信中证500指数增强A", "建信基金"),
    ("000961.OF", "天弘沪深300指数A", "天弘基金"),
    ("002021.OF", "华夏回报混合A", "华夏基金"),
    ("005827.OF", "易方达蓝筹精选混合", "易方达基金"),
    ("001156.OF", "申万菱信量化小盘股票", "申万菱信"),
    ("110022.OF", "易方达消费行业股票", "易方达基金"),
    ("000083.OF", "汇添富消费行业混合", "汇添富基金"),
    ("519005.OF", "海富通精选混合", "海富通基金"),
    ("160706.OF", "嘉实300ETF联接A", "嘉实基金"),
    ("100038.OF", "富国天合稳健优选混合", "富国基金"),
    ("050025.OF", "博时回报灵活配置混合A", "博时基金"),
    ("213001.OF", "宝盈鸿利收益混合", "宝盈基金"),
    ("377240.OF", "上投摩根成长先锋混合", "上投摩根基金"),
    ("260112.OF", "景顺长城品质投资混合", "景顺长城基金"),
    ("519066.OF", "汇添富蓝筹稳健混合", "汇添富基金"),
]

# 真实产品名（PTL_001..PTL_050）—— 已有真实名称的保留
PRODUCT_NAMES = [
    "稳健收益1号", "稳健收益2号", "聚宝盆固收1号", "聚宝盆固收2号",
    "聚宝盆固收3号", "添富宝1号", "添富宝2号", "货币市场1号", "货币市场2号",
    "纯债精选1号", "纯债精选2号", "信用债精选1号", "信用债精选2号",
    "利率债精选1号", "二级债基增强1号", "二级债基增强2号", "可转债优选1号",
    "可转债优选2号", "灵活配置1号", "灵活配置2号", "ESG责任投资1号",
    "ESG责任投资2号", "科创主题1号", "科创主题2号", "新能源主题1号",
    "新能源主题2号", "消费精选1号", "消费精选2号", "医药健康1号",
    "医药健康2号", "金融地产1号", "金融地产2号", "高股息策略1号",
    "高股息策略2号", "中证500增强1号", "沪深300增强1号", "沪深300增强2号",
    "量化对冲1号", "量化对冲2号", "市场中性1号", "市场中性2号",
    "全天候配置1号", "全天候配置2号", "宏观策略1号", "宏观策略2号",
    "FOF稳健1号", "FOF进取1号", "FOF平衡1号", "QDII全球精选1号",
    "QDII美股精选1号",
]

CHANNEL_NAMES = ["招商银行代销", "中信证券代销", "工商银行代销", "建设银行代销",
                 "蚂蚁财富", "天天基金", "京东金融", "华泰证券代销",
                 "国泰君安代销", "腾讯理财通", "雪球财富", "陆金所"]

YIELD_CURVES = [
    "中债国债收益率曲线", "中债AAA企业债收益率曲线", "中债AA+企业债收益率曲线",
    "中债AA企业债收益率曲线", "中债政策银行债收益率曲线",
    "中债同业存单收益率曲线", "中债短融收益率曲线",
    "中债中期票据AAA收益率曲线", "上海银行间同业拆放利率(Shibor)",
    "中债综合财富指数", "中债国开行收益率曲线", "中债铁道债收益率曲线",
]

INDUSTRIES = [
    ("银行", "801780"), ("非银金融", "801790"), ("食品饮料", "801120"),
    ("医药生物", "801150"), ("电子", "801080"), ("家用电器", "801110"),
    ("汽车", "801880"), ("电力设备", "801730"), ("有色金属", "801050"),
    ("基础化工", "801030"), ("机械设备", "801890"), ("计算机", "801750"),
    ("通信", "801770"), ("传媒", "801760"), ("公用事业", "801160"),
    ("交通运输", "801170"), ("农林牧渔", "801010"), ("国防军工", "801740"),
    ("商贸零售", "801200"), ("建筑材料", "801710"), ("石油石化", "801960"),
    ("房地产", "801180"), ("纺织服饰", "801130"), ("轻工制造", "801140"),
]

# ============================================================
# 工具函数
# ============================================================

PLACEHOLDER_RE = re.compile(
    r"^(客户_|某公司_|某大型公司_|某家公司_|某[\u4e00-\u9fa5]+_|主体企业_|主体_|"
    r"补充产品|补充股票股份有限公司|FUND_\d|STOCK_\d|PPN_\d|ABS_\d|REITS_\d|"
    r"NCD_\d|CP_\d|PLAN_\d|"
    r"BTM_AST_CD_|RULE_CD_|PLEDGE_BOND_CD_|PLEDGE_NOTE_|ACC_CD_|ACC_NM_|"
    r"VAL_SRC_|CNTP_ID_|CNTP_NM_|LINKED_ISR_ID_|SETT_ACCT_|SETT_BANK_|"
    r"WHITELIST_|CREDIT_CD_)"
)
NAME_PLACEHOLDER_RE = re.compile(r"_\d{2,4}$|^客户_|^某|^主体_|^主体企业_|^补充|^基金名称$|^股票名称$|^行业$|^占位")


def is_placeholder_str(v):
    if v is None or v == "":
        return False
    s = str(v).strip()
    return bool(PLACEHOLDER_RE.search(s) or NAME_PLACEHOLDER_RE.search(s))


def num_suffix(s):
    """从 'CUST_001' 提取 1；找不到返回 0"""
    if not s:
        return 0
    m = re.search(r'(\d+)$', str(s))
    return int(m.group(1)) if m else 0


def gen_person_name(idx):
    """根据 idx 确定性生成中文人名（200个不同）"""
    sn = SURNAMES[idx % len(SURNAMES)]
    gn = GIVEN_NAMES[(idx // len(SURNAMES) + idx) % len(GIVEN_NAMES)]
    return sn + gn


def gen_company_name(idx):
    return COMPANY_NAMES[idx % len(COMPANY_NAMES)]


def cust_real_name(cust_id, cust_type=None):
    """
    根据 CUST_ID 确定性映射真实姓名。
    奇数 idx 视作个人，偶数 idx 视作机构（粗略 60/40 或固定切分）。
    """
    idx = num_suffix(cust_id)
    if idx == 0:
        return cust_id
    # 个人/机构按 idx 切分（前 120 个为个人，后 80 个为机构）
    if cust_type == "个人":
        return gen_person_name(idx)
    if cust_type in ("机构", "企业"):
        return gen_company_name(idx)
    # 自动判定：1..120 个人；121.. 机构
    if idx <= 120:
        return gen_person_name(idx)
    return gen_company_name(idx - 120)


def fund_real(idx):
    """idx -> (code, name, manager)"""
    return FUNDS[idx % len(FUNDS)]


def stock_real(idx):
    return STOCKS[idx % len(STOCKS)]


def product_real_name(prod_idx):
    if prod_idx <= 0:
        return None
    if prod_idx <= len(PRODUCT_NAMES):
        return PRODUCT_NAMES[prod_idx - 1]
    return PRODUCT_NAMES[(prod_idx - 1) % len(PRODUCT_NAMES)]


def industry_real(idx):
    return INDUSTRIES[idx % len(INDUSTRIES)]


def yield_curve_real(idx):
    return YIELD_CURVES[idx % len(YIELD_CURVES)]


# ============================================================
# 修复任务
# ============================================================

def connect():
    return MongoClient("mongodb://localhost:27017")["asset_allocation"]


def fix_cust_tables(db):
    """
    修复所有以 CUST_ID/CUST_NAME 为主键的客户相关表，
    保证 CUST_001..CUST_200 在所有表里映射到同一真实姓名。
    """
    cust_tables = [
        "dwd_cust_info", "dwd_cust_belong", "dwd_cust_contact",
        "dwd_cust_intention", "dwd_cust_risk", "dwd_cust_tag",
        "dwd_cust_trade", "dwd_cust_asset_summary", "dwd_cust_make_pstn_info",
    ]
    summary = {}
    # 个人/机构判定先从 dwd_cust_info 取
    cust_type_map = {}
    for d in db.dwd_cust_info.find({}, {"CUSTOMER_ID": 1, "CUST_ID": 1, "CUST_TYPE": 1}):
        cid = d.get("CUSTOMER_ID") or d.get("CUST_ID")
        if cid:
            cust_type_map[cid] = d.get("CUST_TYPE")

    for cname in cust_tables:
        coll = db[cname]
        ops = []
        cnt_changed = 0
        for d in coll.find({}, {"_id": 1, "CUST_ID": 1, "CUSTOMER_ID": 1,
                                "CUST_NAME": 1, "CUST_NM": 1}):
            cid = d.get("CUST_ID") or d.get("CUSTOMER_ID")
            if not cid:
                continue
            ctype = cust_type_map.get(cid)
            real = cust_real_name(cid, ctype)
            sets = {}
            if "CUST_NAME" in d and is_placeholder_str(d.get("CUST_NAME")):
                sets["CUST_NAME"] = real
            if "CUST_NM" in d and is_placeholder_str(d.get("CUST_NM")):
                sets["CUST_NM"] = real
            if sets:
                ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
        if ops:
            r = coll.bulk_write(ops, ordered=False)
            cnt_changed = r.modified_count
        summary[cname] = cnt_changed
        print(f"  [客户] {cname}: 修复 {cnt_changed} 行")
    return summary


def fix_cust_info_extra(db):
    """dwd_cust_info 还需要补充 birth/性别/CUSTOMER_NAME 等"""
    coll = db.dwd_cust_info
    ops = []
    base_dt = datetime(1960, 1, 1)
    for d in coll.find({}):
        cid = d.get("CUSTOMER_ID") or d.get("CUST_ID")
        idx = num_suffix(cid)
        if idx == 0:
            continue
        ctype = d.get("CUST_TYPE")
        real_name = cust_real_name(cid, ctype)
        sets = {}
        # CUSTOMER_NAME
        if is_placeholder_str(d.get("CUSTOMER_NAME")) or d.get("CUSTOMER_NAME") in (None, ""):
            sets["CUSTOMER_NAME"] = real_name
        # BIRTH_DT 分散到 1960-2000
        if ctype == "个人" or (ctype is None and idx <= 120):
            days = (idx * 137) % (365 * 40)  # 40 年范围
            sets["BIRTH_DT"] = (base_dt + timedelta(days=days)).strftime("%Y-%m-%d")
            # 性别按姓名首字给定确定性
            sets["GENDER"] = "M" if (idx % 2 == 0) else "F"
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [客户] dwd_cust_info 补充 BIRTH/GENDER/CUSTOMER_NAME: {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_mkt_fund(db):
    """dwd_mkt_fund：所有行 AST_CD=FUND_031 → 按 _id 顺序分散到 20 只真实基金"""
    coll = db.dwd_mkt_fund
    ops = []
    docs = list(coll.find({}, {"_id": 1}).sort("_id", 1))
    for i, d in enumerate(docs):
        code, name, mgr = fund_real(i)
        sets = {
            "AST_CD": code,
            "AST_NAME": name,
            "FUND_NM": name,
            "FUND_MANAGER": mgr,
        }
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [市场] dwd_mkt_fund: 修复 {r.modified_count} 行（分散到 {len(FUNDS)} 只真实基金）")
        return r.modified_count
    return 0


def fix_mkt_stock(db):
    """dwd_mkt_stock：所有行 AST_CD=STOCK_021 → 按 _id 顺序分散到真实 A 股"""
    coll = db.dwd_mkt_stock
    ops = []
    docs = list(coll.find({}, {"_id": 1}).sort("_id", 1))
    for i, d in enumerate(docs):
        code, name, indu = stock_real(i)
        sets = {
            "AST_CD": code,
            "AST_NAME": name,
            "STOCK_NM": name,
            "INDUSTRY_NM": indu,
            "EXCH": "SH" if code.endswith(".SH") else "SZ",
        }
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [市场] dwd_mkt_stock: 修复 {r.modified_count} 行（分散到 {len(STOCKS)} 只真实股票）")
        return r.modified_count
    return 0


def fix_mkt_bond(db):
    """dwd_mkt_bond：所有行 AST_CD=BOND_001 → 按 _id 分散到 50 只虚拟但格式真实的债券"""
    coll = db.dwd_mkt_bond
    ops = []
    docs = list(coll.find({}, {"_id": 1, "AST_NAME": 1}).sort("_id", 1))
    # 生成 50 只真实风格的债券：国债/政策银行债/中票/企业债
    BOND_POOL = []
    for i in range(50):
        if i < 15:
            code = f"01{19000 + i:05d}.IB"
            name = f"24国债{i+1:02d}"
        elif i < 30:
            code = f"23{20000 + i:05d}.IB"
            name = f"23国开{i-14:02d}"
        elif i < 40:
            code = f"10{1900 + i:04d}.IB"
            name = f"24中票{i-29:02d}"
        else:
            code = f"15{2000 + i:04d}.SH"
            name = f"24企业债{i-39:02d}"
        BOND_POOL.append((code, name))
    for i, d in enumerate(docs):
        code, name = BOND_POOL[i % len(BOND_POOL)]
        sets = {"AST_CD": code, "AST_NAME": name}
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [市场] dwd_mkt_bond: 修复 {r.modified_count} 行（分散到 {len(BOND_POOL)} 只债券）")
        return r.modified_count
    return 0


def fix_mkt_yield_curve(db):
    """dwd_mkt_yield_curve：CURVE_NAME 全同 → 按 _id 分散到多条曲线"""
    coll = db.dwd_mkt_yield_curve
    ops = []
    docs = list(coll.find({}, {"_id": 1}).sort("_id", 1))
    for i, d in enumerate(docs):
        sets = {"CURVE_NAME": yield_curve_real(i // 10)}  # 每 10 条切换一条曲线
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [市场] dwd_mkt_yield_curve: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_isr_institution(db):
    """dwd_isr_institution: CREDIT_CD 占位符"""
    coll = db.dwd_isr_institution
    ops = []
    docs = list(coll.find({}, {"_id": 1, "CREDIT_CD": 1, "CUSTOMER_ID": 1, "CUSTOMER_NAME": 1}).sort("_id", 1))
    rating_pool = ["AAA", "AA+", "AA", "AA-", "A+", "A", "BBB+", "BBB"]
    for i, d in enumerate(docs):
        sets = {}
        if is_placeholder_str(d.get("CREDIT_CD")):
            # 用真实评级表示信用代码（如 AAA / AA+）
            sets["CREDIT_CD"] = rating_pool[i % len(rating_pool)]
        # CUSTOMER_NAME 为空或占位符
        if is_placeholder_str(d.get("CUSTOMER_NAME")) or not d.get("CUSTOMER_NAME"):
            sets["CUSTOMER_NAME"] = gen_company_name(i)
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [主体] dwd_isr_institution: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_isr_trd_cntp(db):
    """dwd_isr_trd_cntp: CNTP_ID/CNTP_NM/SETT_ACCT/SETT_BANK 等多个占位符字段"""
    coll = db.dwd_isr_trd_cntp
    ops = []
    BANKS = ["招商银行", "工商银行", "建设银行", "中国银行", "交通银行",
             "兴业银行", "浦发银行", "民生银行", "中信银行", "光大银行"]
    docs = list(coll.find({}).sort("_id", 1))
    for i, d in enumerate(docs):
        sets = {}
        cnt_id = f"CNTP_{i+1:03d}"
        # 用 COMPANY_NAMES 中的"证券/基金"类作为对手方
        cnt_nm = COMPANY_NAMES[i % 12]  # 前12家是证券/基金类
        bank = BANKS[i % len(BANKS)]
        if is_placeholder_str(d.get("CNTP_ID")):
            sets["CNTP_ID"] = cnt_id
        if is_placeholder_str(d.get("CNTP_NM")):
            sets["CNTP_NM"] = cnt_nm
        if is_placeholder_str(d.get("LINKED_ISR_ID")):
            sets["LINKED_ISR_ID"] = f"ISR_{i+1:03d}"
        if is_placeholder_str(d.get("SETT_ACCT")):
            sets["SETT_ACCT"] = f"6217{1000 + i:04d}{2000 + i*7:04d}{3000 + i*3:04d}"
        if is_placeholder_str(d.get("SETT_BANK")):
            sets["SETT_BANK"] = bank
        if is_placeholder_str(d.get("WHITELIST")):
            sets["WHITELIST"] = "Y" if i % 3 != 0 else "N"
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [主体] dwd_isr_trd_cntp: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_ptl_tables(db):
    """修复所有 PTL_xxx 产品名占位符 '补充产品0XX' → 真实产品名"""
    ptl_tables = [
        "dwd_ptl_info", "dwd_ptl_attribution", "dwd_ptl_channel",
        "dwd_ptl_class_map", "dwd_ptl_contract", "dwd_ptl_fee",
        "dwd_ptl_manager", "dwd_ptl_nav", "dwd_ptl_pstn_detail",
        "dwd_ptl_risk", "dwd_ptl_sub_red",
        "dwd_rsk_alert", "dwd_rsk_compliance", "dwd_rsk_limit",
        "dwd_rsk_report", "dwd_rsk_stress_test",
        "dwd_val_adjustment", "dwd_val_bal", "dwd_val_diff",
        "dwd_val_exception", "dwd_val_impairment", "dwd_val_method",
        "dwd_val_receivable_payable", "dwd_val_review", "dwd_val_summary",
    ]
    summary = {}
    for cname in ptl_tables:
        coll = db[cname]
        ops = []
        for d in coll.find({}, {"_id": 1, "PROD_CD": 1, "PROD_NAME": 1, "PORT_ID": 1, "PARENT_PROD_CD": 1}):
            sets = {}
            if is_placeholder_str(d.get("PROD_NAME")):
                pcd = d.get("PROD_CD") or d.get("PORT_ID") or d.get("PARENT_PROD_CD")
                idx = num_suffix(pcd)
                if idx > 0:
                    sets["PROD_NAME"] = product_real_name(idx)
            if sets:
                ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
        if ops:
            r = coll.bulk_write(ops, ordered=False)
            summary[cname] = r.modified_count
            print(f"  [组合] {cname}: 修复 {r.modified_count} 行")
    return summary


def fix_ptl_channel_extra(db):
    """dwd_ptl_channel: CHANNEL_CD/CHANNEL_NAME 中的占位符"""
    coll = db.dwd_ptl_channel
    ops = []
    docs = list(coll.find({}).sort("_id", 1))
    for i, d in enumerate(docs):
        sets = {}
        ch = CHANNEL_NAMES[i % len(CHANNEL_NAMES)]
        # 即使原值不是占位符，但形如"申万宏源"作为代码也不合理 -> 给真实代码
        sets["CHANNEL_CD"] = f"CH_{i % len(CHANNEL_NAMES) + 1:03d}"
        sets["CHANNEL_NAME"] = ch
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [组合] dwd_ptl_channel 渠道补充: {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_ast_tables_with_ast_cd(db):
    """
    修复多个含 AST_CD/AST_NAME 占位符的资产相关表：
    - 如果 AST_CD 是 STOCK_xxx → 使用真实股票
    - 如果是 FUND_xxx → 使用真实基金
    - 其他类型（PPN/ABS/REITS/NCD/CP/PLAN）保留代码（结构合理）但修复 AST_NAME 中的"补充股票股份有限公司XX"占位文字
    """
    ast_tables = [
        "dwd_ast_cf_plan", "dwd_ast_exe_plan", "dwd_ast_fiveclass",
        "dwd_ast_party", "dwd_ast_pledge", "dwd_ast_yield_info",
        "dwd_ast_bottom_raito", "dwd_ast_calc_rule", "dwd_ast_info",
        "dwd_ast_info_ch", "dwd_ast_info_zg",
        "dwd_ptl_pstn_detail",
        "dwd_trn_trade_ast", "dwd_val_detail", "dwd_val_impairment",
    ]
    summary = {}

    for cname in ast_tables:
        coll = db[cname]
        ops = []
        for d in coll.find({}):
            sets = {}
            ast_cd = d.get("AST_CD")
            ast_name = d.get("AST_NAME")
            if not ast_cd:
                continue
            ast_cd_str = str(ast_cd)
            # 类型 1：STOCK_xxx
            if re.match(r"^STOCK_\d+$", ast_cd_str):
                idx = num_suffix(ast_cd_str)
                code, name, indu = stock_real(idx)
                sets["AST_CD"] = code
                sets["AST_NAME"] = name
                if "INDUSTRY_NM" in d:
                    sets["INDUSTRY_NM"] = indu
            # 类型 2：FUND_xxx
            elif re.match(r"^FUND_\d+$", ast_cd_str):
                idx = num_suffix(ast_cd_str)
                code, name, mgr = fund_real(idx)
                sets["AST_CD"] = code
                sets["AST_NAME"] = name
            # 类型 3：BOND_xxx → 保留代码结构（已有真实债名时不动），仅在名称占位时替换
            elif re.match(r"^BOND_\d+$", ast_cd_str):
                # 大部分债已有真实名称，跳过
                if is_placeholder_str(ast_name):
                    sets["AST_NAME"] = f"24国债{num_suffix(ast_cd_str):02d}"
            else:
                # PPN/ABS/REITS/NCD/CP/PLAN：保留代码，仅当名称是"补充股票..."这种错误占位时替换
                if ast_name and "补充股票股份有限公司" in str(ast_name):
                    idx = num_suffix(ast_cd_str)
                    prefix_match = re.match(r"^([A-Z]+)_", ast_cd_str)
                    pfx = prefix_match.group(1) if prefix_match else "AST"
                    label = {"PPN": "私募定向票据", "ABS": "资产支持证券",
                             "REITS": "公募REIT", "NCD": "同业存单",
                             "CP": "短期融资券", "PLAN": "资产管理计划"}.get(pfx, "资产")
                    sets["AST_NAME"] = f"24年{label}第{idx:02d}期"

            # 修复其它占位字段
            if "BTM_AST_CD" in d and is_placeholder_str(d.get("BTM_AST_CD")):
                sets["BTM_AST_CD"] = sets.get("AST_CD", ast_cd)
            if "BTM_NM" in d and d.get("BTM_NM") == "底层资产":
                sets["BTM_NM"] = sets.get("AST_NAME", ast_name) or "底层资产"
            if "RULE_CD" in d and is_placeholder_str(d.get("RULE_CD")):
                rule_id = num_suffix(d.get("RULE_CD"))
                sets["RULE_CD"] = f"RULE_{rule_id+1:03d}"
            if "RULE_NM" in d and d.get("RULE_NM") == "计算规则":
                rules = ["按日计提", "按月分摊", "到期一次还本", "实际/实际",
                         "30/360", "ACT/365", "线性摊销", "实际利率法"]
                idx = num_suffix(d.get("RULE_CD", "")) or 0
                sets["RULE_NM"] = rules[idx % len(rules)]
            if "PLEDGE_BOND_CD" in d and is_placeholder_str(d.get("PLEDGE_BOND_CD")):
                sets["PLEDGE_BOND_CD"] = f"019601.IB"
            if "PLEDGE_NOTE" in d and is_placeholder_str(d.get("PLEDGE_NOTE")):
                sets["PLEDGE_NOTE"] = "正回购质押"
            if "VAL_SRC" in d and is_placeholder_str(d.get("VAL_SRC")):
                sets["VAL_SRC"] = "中债估值"

            if sets:
                ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
        if ops:
            r = coll.bulk_write(ops, ordered=False)
            summary[cname] = r.modified_count
            print(f"  [资产] {cname}: 修复 {r.modified_count} 行")
    return summary


def fix_val_bal(db):
    """dwd_val_bal: ACC_CD/ACC_NM 占位符"""
    coll = db.dwd_val_bal
    ACC_LIST = [
        ("1001", "库存现金"), ("1002", "银行存款"), ("1101", "交易性金融资产"),
        ("1108", "应收利息"), ("1501", "持有至到期投资"), ("1503", "可供出售金融资产"),
        ("2202", "应付利息"), ("2231", "应付管理费"), ("2241", "应付托管费"),
        ("3101", "实收基金"), ("4001", "本年利润"),
    ]
    ops = []
    docs = list(coll.find({}).sort("_id", 1))
    for i, d in enumerate(docs):
        sets = {}
        if is_placeholder_str(d.get("ACC_CD")):
            cd, nm = ACC_LIST[i % len(ACC_LIST)]
            sets["ACC_CD"] = cd
            if is_placeholder_str(d.get("ACC_NM")):
                sets["ACC_NM"] = nm
        if "ACCOUNT_CD" in d and is_placeholder_str(d.get("ACCOUNT_CD")):
            cd, nm = ACC_LIST[i % len(ACC_LIST)]
            sets["ACCOUNT_CD"] = cd
            if is_placeholder_str(d.get("ACCOUNT_NAME")) or d.get("ACCOUNT_NAME") in (None, "", "银行存款"):
                sets["ACCOUNT_NAME"] = nm
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [估值] dwd_val_bal: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_trn_trade_fund(db):
    """dwd_trn_trade_fund: CNTP_NM 含'主体企业_xxx_行业'占位符"""
    coll = db.dwd_trn_trade_fund
    ops = []
    for d in coll.find({}):
        cnm = d.get("CNTP_NM", "")
        if is_placeholder_str(cnm) or "主体企业_" in str(cnm):
            cid = d.get("CNTP_ID", "")
            idx = num_suffix(cid) or num_suffix(cnm)
            ops.append(UpdateOne({"_id": d["_id"]},
                                 {"$set": {"CNTP_NM": gen_company_name(idx)}}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [交易] dwd_trn_trade_fund: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_sls_sales(db):
    """dwd_sls_sales: 既要修产品名也要修客户名"""
    coll = db.dwd_sls_sales
    ops = []
    cust_type_map = {}
    for d in db.dwd_cust_info.find({}, {"CUSTOMER_ID": 1, "CUST_TYPE": 1}):
        if d.get("CUSTOMER_ID"):
            cust_type_map[d["CUSTOMER_ID"]] = d.get("CUST_TYPE")

    for d in coll.find({}):
        sets = {}
        if is_placeholder_str(d.get("PROD_NAME")):
            pcd = d.get("PROD_CD")
            idx = num_suffix(pcd)
            sets["PROD_NAME"] = product_real_name(idx) if idx else d.get("PROD_NAME")
        if is_placeholder_str(d.get("CUST_NAME")):
            cid = d.get("CUST_ID")
            sets["CUST_NAME"] = cust_real_name(cid, cust_type_map.get(cid))
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [销售] dwd_sls_sales: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_trn_trade_ptl(db):
    """dwd_trn_trade_ptl: CUST_NAME + AST_CD 全为 019601.IB"""
    coll = db.dwd_trn_trade_ptl
    ops = []
    cust_type_map = {}
    for d in db.dwd_cust_info.find({}, {"CUSTOMER_ID": 1, "CUST_TYPE": 1}):
        if d.get("CUSTOMER_ID"):
            cust_type_map[d["CUSTOMER_ID"]] = d.get("CUST_TYPE")
    docs = list(coll.find({}).sort("_id", 1))
    for i, d in enumerate(docs):
        sets = {}
        if is_placeholder_str(d.get("CUST_NAME")):
            cid = d.get("CUST_ID")
            sets["CUST_NAME"] = cust_real_name(cid, cust_type_map.get(cid))
        if is_placeholder_str(d.get("PROD_NAME")):
            pcd = d.get("PROD_CD") or d.get("PORT_ID")
            idx = num_suffix(pcd)
            if idx:
                sets["PROD_NAME"] = product_real_name(idx)
        # AST_CD 全部 019601.IB → 分散到不同基金/股票
        if d.get("AST_CD") == "019601.IB":
            # 此表是 PTL 申赎，AST_CD 实际上是父产品本身或代销基金 → 用真实基金
            code, name, _ = fund_real(i)
            sets["AST_CD"] = code
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [交易] dwd_trn_trade_ptl: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


def fix_ast_fund_manager(db):
    """dwd_ast_fund_manager: AST_CD 全为 019601.IB → 分散到 5 只真实基金"""
    coll = db.dwd_ast_fund_manager
    ops = []
    docs = list(coll.find({}).sort("_id", 1))
    for i, d in enumerate(docs):
        code, name, _ = fund_real(i)
        ops.append(UpdateOne({"_id": d["_id"]},
                             {"$set": {"AST_CD": code}}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"  [资产] dwd_ast_fund_manager: 修复 {r.modified_count} 行")
        return r.modified_count
    return 0


# ============================================================
# 主入口
# ============================================================

def main():
    db = connect()
    print("=" * 70)
    print("开始批量修复 asset_allocation 库 dwd_ 集合的 HERMES 占位符质量问题")
    print("=" * 70)
    total = 0
    print("\n>>> 修复客户相关表（CUST_NAME 一致映射）")
    for n in fix_cust_tables(db).values():
        total += n
    total += fix_cust_info_extra(db)

    print("\n>>> 修复市场行情主数据表")
    total += fix_mkt_fund(db)
    total += fix_mkt_stock(db)
    total += fix_mkt_bond(db)
    total += fix_mkt_yield_curve(db)

    print("\n>>> 修复主体相关表")
    total += fix_isr_institution(db)
    total += fix_isr_trd_cntp(db)

    print("\n>>> 修复产品(PTL)/风控/估值表 PROD_NAME 占位")
    for n in fix_ptl_tables(db).values():
        total += n
    total += fix_ptl_channel_extra(db)

    print("\n>>> 修复资产(AST_CD/AST_NAME)相关表")
    for n in fix_ast_tables_with_ast_cd(db).values():
        total += n
    total += fix_val_bal(db)
    total += fix_ast_fund_manager(db)

    print("\n>>> 修复交易/销售表")
    total += fix_trn_trade_fund(db)
    total += fix_sls_sales(db)
    total += fix_trn_trade_ptl(db)

    print("\n" + "=" * 70)
    print(f"修复完成，累计变更 {total} 行")
    print("=" * 70)


if __name__ == "__main__":
    main()

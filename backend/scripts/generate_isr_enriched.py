"""
Task 2: 扩充 dwd_isr_institution 主体基表
从现有30条扩充到60+条，覆盖12个行业、20个省份、4种企业性质。
确保与后续 subject_risk_records 新增的 subject_name 100% 对齐。
"""
import sys
import random
from datetime import datetime

sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

random.seed(42)

# ─── 配置 ───────────────────────────────────────────────────────────────
DB_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
COLLECTION = "dwd_isr_institution"

# 行业-地域-性质联动种子
INDUSTRY_SEEDS = {
    "房地产业-房地产开发经营": {
        "provinces": ["广东省", "北京市", "上海市", "江苏省", "浙江省"],
        "natures": ["民营企业", "国有企业", "混合所有制"],
        "companies": [
            ("融创中国控股有限公司", "融创中国"),
            ("龙湖集团控股有限公司", "龙湖集团"),
            ("华润置地有限公司", "华润置地"),
            ("中海地产集团有限公司", "中海地产"),
            ("新城控股集团股份有限公司", "新城控股"),
        ],
    },
    "建筑业-土木工程建筑业": {
        "provinces": ["北京市", "上海市", "湖北省", "四川省"],
        "natures": ["国有企业", "混合所有制"],
        "companies": [
            ("中国建筑集团有限公司", "中国建筑"),
            ("中国电建集团有限公司", "中国电建"),
            ("上海建工集团股份有限公司", "上海建工"),
        ],
    },
    "金融业-货币金融服务": {
        "provinces": ["北京市", "上海市", "广东省"],
        "natures": ["国有企业", "混合所有制"],
        "companies": [
            ("中国农业银行股份有限公司", "农业银行"),
            ("中国建设银行股份有限公司", "建设银行"),
            ("兴业银行股份有限公司", "兴业银行"),
        ],
    },
    "金融业-资本市场服务": {
        "provinces": ["北京市", "上海市", "广东省", "浙江省"],
        "natures": ["国有企业", "民营企业"],
        "companies": [
            ("华泰证券股份有限公司", "华泰证券"),
            ("国泰君安证券股份有限公司", "国泰君安"),
            ("东方财富信息股份有限公司", "东方财富"),
        ],
    },
    "金融业-保险业": {
        "provinces": ["北京市", "上海市", "广东省"],
        "natures": ["国有企业", "混合所有制"],
        "companies": [
            ("中国人寿保险股份有限公司", "中国人寿"),
            ("中国太平洋保险(集团)股份有限公司", "太平洋保险"),
        ],
    },
    "信息传输、软件和信息技术服务业": {
        "provinces": ["广东省", "北京市", "浙江省", "江苏省"],
        "natures": ["民营企业", "外商投资企业"],
        "companies": [
            ("腾讯控股有限公司", "腾讯控股"),
            ("百度集团股份有限公司", "百度集团"),
            ("字节跳动有限公司", "字节跳动"),
            ("小米集团有限公司", "小米集团"),
        ],
    },
    "制造业-汽车制造业": {
        "provinces": ["广东省", "上海市", "安徽省", "湖北省"],
        "natures": ["国有企业", "民营企业", "外商投资企业"],
        "companies": [
            ("比亚迪股份有限公司", "比亚迪"),
            ("上海汽车集团股份有限公司", "上汽集团"),
            ("蔚来控股有限公司", "蔚来汽车"),
        ],
    },
    "制造业-医药制造业": {
        "provinces": ["江苏省", "浙江省", "上海市", "北京市"],
        "natures": ["民营企业", "混合所有制"],
        "companies": [
            ("恒瑞医药股份有限公司", "恒瑞医药"),
            ("药明康德新药开发股份有限公司", "药明康德"),
            ("迈瑞医疗国际股份有限公司", "迈瑞医疗"),
        ],
    },
    "批发和零售业": {
        "provinces": ["浙江省", "广东省", "北京市", "上海市"],
        "natures": ["民营企业", "外商投资企业"],
        "companies": [
            ("京东集团股份有限公司", "京东集团"),
            ("拼多多控股有限公司", "拼多多"),
        ],
    },
    "交通运输、仓储和邮政业": {
        "provinces": ["北京市", "上海市", "广东省", "四川省"],
        "natures": ["国有企业"],
        "companies": [
            ("中国国际航空股份有限公司", "中国国航"),
            ("中远海运控股股份有限公司", "中远海控"),
            ("顺丰控股股份有限公司", "顺丰控股"),
        ],
    },
    "电力、热力、燃气及水生产和供应业": {
        "provinces": ["北京市", "广东省", "湖北省", "云南省"],
        "natures": ["国有企业"],
        "companies": [
            ("国家电力投资集团有限公司", "国家电投"),
            ("中国华能集团有限公司", "华能集团"),
        ],
    },
    "农、林、牧、渔业": {
        "provinces": ["山东省", "河南省", "四川省", "广西壮族自治区"],
        "natures": ["民营企业", "国有企业"],
        "companies": [
            ("牧原食品股份有限公司", "牧原股份"),
            ("新希望六和股份有限公司", "新希望"),
        ],
    },
}

CREDIT_CODES = ["AAA", "AA+", "AA", "AA-", "A+", "A", "BBB+", "BBB"]


def generate_isr_id(index: int) -> str:
    return f"ISR{str(index).zfill(6)}"


def build_new_institutions():
    """生成新增主体文档列表"""
    new_docs = []
    idx = 31  # 从31开始（现有30条用ISR000001-ISR000030）

    for industry, cfg in INDUSTRY_SEEDS.items():
        for company_name, short_name in cfg["companies"]:
            province = random.choice(cfg["provinces"])
            nature = random.choice(cfg["natures"])
            credit = random.choice(CREDIT_CODES[:5])  # 大企业评级偏高

            doc = {
                "ISR_ID": generate_isr_id(idx),
                "ISR_NM": company_name,
                "ISR_SHORT_NM": short_name,
                "ISR_TYPE": "企业法人",
                "COMPANY_NATURE": nature,
                "PROVINCE": province,
                "CITY": "",
                "COUNTY": "",
                "INDUSTRY_GB2": industry,
                "INDUSTRY_SW": industry.split("-")[0] if "-" in industry else industry,
                "INDUSTRY_SW2": industry,
                "INDUSTRY_WIND": industry.split("-")[0] if "-" in industry else industry,
                "INDUSTRY_WIND2": industry,
                "INDUSTRY_ZJH": industry.split("-")[0] if "-" in industry else industry,
                "INDUSTRY_ZJH2": industry,
                "INDUSTRY_ZJH3": "",
                "INDUSTRY_CH": industry.split("-")[0] if "-" in industry else industry,
                "INDUSTRY_CH2": industry,
                "INDUSTRY_CD": f"IND{str(idx).zfill(4)}",
                "CREDIT_CD": credit,
                "BANK_TYPE": "非银行" if "金融" not in industry else "银行",
                "IS_JRJG": "是" if "金融" in industry else "否",
                "JRJG_TYPE": "银行" if "货币" in industry else ("证券" if "资本" in industry else ("保险" if "保险" in industry else "")),
                "IS_DEFAULT": "否",
                "LIST_FLAG": random.choice(["已上市", "未上市"]),
                "CHENG_TOU_FALG": "否",
                "ORG_TYPE_FC": nature,
                "REG_CAP_AMT": random.randint(100000, 50000000) * 10000,
                "REG_PROV": province,
                "CUSTOMER_NAME": company_name,
                "CUSTOMER_ABBR": short_name,
                "EST_DT": f"{random.randint(1990, 2015)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
                "BIZ_DT": "2026-05-26",
                "DATA_SRC": "WIND",
                "DATA_TIME": "08:00:00",
                "IMPORT_TYPE": "full",
                "src_sys": "hermes_enriched",
                "etl_dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            new_docs.append(doc)
            idx += 1

    return new_docs


def main():
    client = MongoClient(DB_URI)
    db = client[DB_NAME]
    col = db[COLLECTION]

    # 查现有数据
    existing_count = col.count_documents({})
    existing_names = set(col.distinct("ISR_NM"))
    print(f"现有 dwd_isr_institution: {existing_count} 条, {len(existing_names)} 个独立主体")

    new_docs = build_new_institutions()

    # 过滤已存在的
    to_insert = [d for d in new_docs if d["ISR_NM"] not in existing_names]
    print(f"待插入: {len(to_insert)} 条（已过滤 {len(new_docs) - len(to_insert)} 条重复）")

    if to_insert:
        result = col.insert_many(to_insert)
        print(f"插入完成: {len(result.inserted_ids)} 条")

    final_count = col.count_documents({})
    final_names = col.distinct("ISR_NM")
    print(f"最终 dwd_isr_institution: {final_count} 条, {len(final_names)} 个独立主体")

    # 输出行业分布
    pipeline = [{"$group": {"_id": "$INDUSTRY_GB2", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    print("\n行业分布:")
    for d in col.aggregate(pipeline):
        print(f"  {d['_id']}: {d['count']}")

    client.close()


if __name__ == "__main__":
    main()

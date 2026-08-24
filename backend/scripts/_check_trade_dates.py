"""对比原型和监测系统的交易日历"""
import pandas as pd
import asyncio, sys
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
from app.config.database import Database

# 原型交易日历
proto_td = pd.read_excel(r'd:\project\portfilio\大类资产模型研究实验最新在用\raw_data\trade_dates.xlsx')
proto_td['trade_dates'] = pd.to_datetime(proto_td['trade_dates'])
proto_list = sorted(proto_td['trade_dates'].tolist())
proto_set = set(proto_list)

# 监测系统交易日历
async def get_trade_dates():
    Database.connect()
    db = Database.db
    docs = await db['trade_dates'].find({}, {"_id": 0}).to_list(length=10000)
    return docs

docs = asyncio.run(get_trade_dates())
if docs:
    mongo_dates = sorted([pd.Timestamp(d.get('date') or d.get('trade_date')) for d in docs])
    print(f"集合: trade_dates, 字段: {list(docs[0].keys())}")
else:
    # 可能是其他集合名
    colls = asyncio.run(Database.db.list_collection_names())
    print(f"集合列表: {colls}")
    mongo_dates = []

mongo_set = set(mongo_dates)

print(f"原型交易日数: {len(proto_list)}")
print(f"监测交易日数: {len(mongo_dates)}")

only_proto = sorted(proto_set - mongo_set)
only_mongo = sorted(mongo_set - proto_set)
print(f"仅原型: {len(only_proto)}")
print(f"仅监测: {len(only_mongo)}")

if only_proto:
    print(f"  仅原型的前10: {[str(d.date()) for d in only_proto[:10]]}")
if only_mongo:
    print(f"  仅监测的前10: {[str(d.date()) for d in only_mongo[:10]]}")

# 检查2014-2015年区间
proto_2014 = [d for d in proto_list if pd.Timestamp('2014-01-01') <= d <= pd.Timestamp('2015-12-31')]
mongo_2014 = [d for d in mongo_dates if pd.Timestamp('2014-01-01') <= d <= pd.Timestamp('2015-12-31')]
print(f"\n2014-2015年: 原型={len(proto_2014)}, 监测={len(mongo_2014)}")
diff_2014 = set(proto_2014) ^ set(mongo_2014)
if diff_2014:
    print(f"  差异日期: {[str(d.date()) for d in sorted(diff_2014)]}")
else:
    print("  2014-2015年交易日完全一致")

"""对比原型权重与MongoDB预计算权重（检查映射是否正确）"""
import pandas as pd
import asyncio, sys, json
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
from app.config.database import Database

# 读取原型权重
weights_path = r'd:\project\portfilio\大类资产模型研究实验最新在用\results\权重计算结果.xlsx'
weights_df = pd.read_excel(weights_path, sheet_name='权重矩阵')
weights_df['计算日期'] = pd.to_datetime(weights_df['计算日期'])

# 中文→代码映射
SHARPE_NAME_TO_CODE = {
    '沪深300': 'SH000300', '中证500': 'ZZ000905', '创业板指': 'SZ399006',
    '标普500': 'SPX', '纳斯达克100': 'NDX', '日经225': 'N225',
    '中国10年国债': 'ZQGZ10', '中国5年国债': 'ZQGZ5', '中国2年国债': 'ZQGZ2',
    '美国10年国债': 'UST10', '美国2年国债': 'UST2',
    '可转债': 'CVTBND', '黄金': 'GLD', '布伦特原油': 'B00Y',
    '沪铜': 'SHCU', '沪铝': 'SHAL', '沪锡': 'SHSN', '豆粕': 'DM',
}
ASSET_NAMES = ['中国10年国债', '中国5年国债', '中国2年国债', '美国10年国债', '美国2年国债',
               '可转债', '沪深300', '中证500', '创业板指', '标普500', '纳斯达克100', '日经225',
               '沪铜', '沪铝', '沪锡', '黄金', '布伦特原油', '豆粕']

async def get_mongo_weights():
    Database.connect()
    db = Database.db
    docs = await db['sharpe_rebalance_weights'].find(
        {"monitor_id": "6a2b8d5fb67c1b1b54540b0d"}
    ).to_list(length=None)
    result = {}
    for doc in docs:
        result[doc['calc_date']] = doc['weights']
    return result

mongo_weights = asyncio.run(get_mongo_weights())
print(f"原型权重数: {len(weights_df)}")
print(f"MongoDB权重数: {len(mongo_weights)}")

# 对比前5个和后5个
mismatches = 0
for i, row in weights_df.iterrows():
    calc_date = row['计算日期']
    calc_date_str = calc_date.strftime('%Y-%m-%d')
    
    # 原型权重
    proto_weights = {name: row.get(name, 0.0) for name in ASSET_NAMES}
    
    # MongoDB权重（键名可能是中文或资产代码）
    mongo_w = mongo_weights.get(calc_date_str, None)
    if mongo_w is None:
        continue
    
    # 检查MongoDB键名格式
    first_key = next(iter(mongo_w))
    if first_key in SHARPE_NAME_TO_CODE:
        # 中文名，需要转换
        mongo_weights_code = {SHARPE_NAME_TO_CODE.get(k, k): v for k, v in mongo_w.items()}
    else:
        mongo_weights_code = mongo_w
    
    # 对比
    for cn_name, code in SHARPE_NAME_TO_CODE.items():
        pw = proto_weights.get(cn_name, 0.0)
        mw = mongo_weights_code.get(code, 0.0)
        if abs(pw - mw) > 1e-8:
            if mismatches < 30:
                print(f"MISMATCH: date={calc_date_str}, asset={cn_name}({code}), proto={pw:.8f}, mongo={mw:.8f}")
            mismatches += 1

print(f"\n总不匹配数: {mismatches}")
if mismatches == 0:
    print("所有权重完全一致！")

# 输出前3个月末日的详细权重
print("\n=== 前3个调仓日详细权重对比 ===")
for i in range(min(3, len(weights_df))):
    row = weights_df.iloc[i]
    calc_date_str = row['计算日期'].strftime('%Y-%m-%d')
    print(f"\n--- 计算日: {calc_date_str} ---")
    mongo_w = mongo_weights.get(calc_date_str, {})
    first_key = next(iter(mongo_w), None) if mongo_w else None
    if first_key and first_key in SHARPE_NAME_TO_CODE:
        mongo_w_code = {SHARPE_NAME_TO_CODE.get(k, k): v for k, v in mongo_w.items()}
    else:
        mongo_w_code = mongo_w
    
    for cn_name, code in SHARPE_NAME_TO_CODE.items():
        pw = row.get(cn_name, 0.0)
        mw = mongo_w_code.get(code, 0.0)
        if pw != 0 or mw != 0:
            print(f"  {cn_name:12s} ({code:8s}) | proto={pw:10.6f} | mongo={mw:10.6f}")

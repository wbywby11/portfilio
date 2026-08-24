"""对比原型Excel费率与监测系统config硬编码费率"""
import pandas as pd
import sys
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
from app.monitor import config as mconfig

# 读取原型费率
fee_path = r'd:\project\portfilio\大类资产模型研究实验最新在用\raw_data\资产费用.xlsx'
fee_df = pd.read_excel(fee_path)
print(fee_df.to_string())

print("\n=== 对比交易费率 ===")
print(f"{'资产':15s} | {'Excel费率':>10s} | {'config费率':>10s} | {'差异':>10s}")
for _, row in fee_df.iterrows():
    asset = row['资产']
    excel_tc = row['交易费用']
    config_tc = mconfig.SHARPE_TRADING_COST.get(asset, None)
    diff = "" if config_tc is None else f"{excel_tc - config_tc:.6f}"
    mark = " ***" if diff and float(diff) != 0 else ""
    print(f"{asset:15s} | {excel_tc:10.6f} | {str(config_tc):>10s} | {diff:>10s}{mark}")

print("\n=== 对比复制费率 ===")
print(f"{'资产':15s} | {'Excel费率':>10s} | {'config费率':>10s} | {'差异':>10s}")
for _, row in fee_df.iterrows():
    asset = row['资产']
    excel_rc = row['复制费用']
    config_rc = mconfig.SHARPE_REPLICATION_COST.get(asset, None)
    diff = "" if config_rc is None else f"{excel_rc - config_rc:.6f}"
    mark = " ***" if diff and float(diff) != 0 else ""
    print(f"{asset:15s} | {excel_rc:10.6f} | {str(config_rc):>10s} | {diff:>10s}{mark}")

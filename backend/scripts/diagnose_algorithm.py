"""
诊断算法权重计算问题的脚本
检查为什么算法总是返回等权重
"""
import sys
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, 'd:/workSpace/portfilio-end')

from app.services.asset_service import AssetService
from app.algorithms.mean_variance import MeanVarianceAlgorithm
from app.algorithms.min_variance import MinVarianceAlgorithm
from app.algorithms.risk_parity import RiskParityAlgorithm
from app.algorithms.momentum import MomentumAlgorithm


async def diagnose_algorithm():
    """诊断算法问题"""
    
    print("=" * 80)
    print("算法权重诊断工具")
    print("=" * 80)
    print()
    
    # 获取资产服务
    asset_service = AssetService()
    
    # 测试资产代码
    asset_codes = ["000300.SH", "000905.SH", "H11001.CSI"]
    
    # 测试日期范围（最近1年）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    print(f"📊 获取测试数据")
    print(f"   资产: {asset_codes}")
    print(f"   日期范围: {start_date.date()} 至 {end_date.date()}")
    print()
    
    # 获取价格数据
    price_df = await asset_service.get_price_dataframe(
        asset_codes,
        start_date,
        end_date
    )
    
    if price_df.empty:
        print("❌ 无法获取价格数据！")
        return
    
    print(f"✅ 成功获取价格数据")
    print(f"   数据行数: {len(price_df)}")
    print(f"   数据列数: {len(price_df.columns)}")
    print(f"   数据范围: {price_df.index[0]} 至 {price_df.index[-1]}")
    print()
    
    # 检查数据质量
    print("📈 数据质量检查")
    print(f"   缺失值数量: {price_df.isnull().sum().sum()}")
    print(f"   数据统计:")
    print(price_df.describe())
    print()
    
    # 计算收益率统计
    returns = price_df.pct_change().dropna()
    print("📊 收益率统计")
    print(f"   收益率数据行数: {len(returns)}")
    print(f"   平均收益率:")
    print(returns.mean())
    print()
    print(f"   收益率标准差:")
    print(returns.std())
    print()
    
    # 计算协方差矩阵
    cov_matrix = returns.cov()
    print("📐 协方差矩阵:")
    print(cov_matrix)
    print()
    print(f"   协方差矩阵行列式: {np.linalg.det(cov_matrix.values)}")
    print(f"   协方差矩阵条件数: {np.linalg.cond(cov_matrix.values)}")
    print()
    
    # 测试各个算法
    algorithms = [
        ("均值方差", MeanVarianceAlgorithm, {'risk_aversion': 1.0}),
        ("最小方差", MinVarianceAlgorithm, {}),
        ("风险平价", RiskParityAlgorithm, {}),
        ("动量配置", MomentumAlgorithm, {'lookback_period': 60}),
    ]
    
    print("=" * 80)
    print("算法权重测试")
    print("=" * 80)
    print()
    
    for algo_name, algo_class, params in algorithms:
        print(f"🔬 测试算法: {algo_name}")
        print(f"   参数: {params}")
        
        try:
            # 创建算法实例
            algorithm = algo_class(params)
            
            # 计算权重
            weights = algorithm.calculate_weights(price_df)
            
            print(f"   计算结果:")
            for asset, weight in weights.items():
                print(f"      {asset}: {weight:.4f} ({weight*100:.2f}%)")
            
            # 检查是否为等权
            n_assets = len(weights)
            equal_weight = 1.0 / n_assets
            is_equal = all(abs(w - equal_weight) < 0.001 for w in weights.values())
            
            if is_equal:
                print(f"   ⚠️  警告: 返回的是等权重配置！")
            else:
                print(f"   ✅ 成功计算出差异化权重")
            
        except Exception as e:
            print(f"   ❌ 错误: {str(e)}")
            import traceback
            traceback.print_exc()
        
        print()
    
    print("=" * 80)
    print("诊断建议")
    print("=" * 80)
    print()
    
    if len(returns) < 60:
        print("⚠️  数据量较少（< 60天），可能影响优化效果")
        print("   建议: 增加回测开始日期，获取更多历史数据")
        print()
    
    if np.linalg.cond(cov_matrix.values) > 1000:
        print("⚠️  协方差矩阵条件数较大，可能存在数值不稳定")
        print("   建议: 检查数据是否有异常值或极端波动")
        print()
    
    if abs(np.linalg.det(cov_matrix.values)) < 1e-10:
        print("⚠️  协方差矩阵接近奇异，可能影响优化")
        print("   建议: 检查资产之间是否高度相关")
        print()


if __name__ == "__main__":
    asyncio.run(diagnose_algorithm())

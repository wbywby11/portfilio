"""常驻回归测试套件：fixture / chains / compare / run_regression。

用途：改回测/监控/服务层代码后，用一条命令确认数值行为未漂移。
    py tests\\regression\\run_regression.py rebase   # 重建黄金基线
    py tests\\regression\\run_regression.py check    # 对比黄金基线
"""

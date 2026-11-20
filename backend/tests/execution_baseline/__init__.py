# -*- coding: utf-8 -*-
"""统一零漂移基线系统（替代旧的 execution_parity + regression snapshot 两套快照）.

三层结构
--------
1. ``engine``     —— 引擎层 parity：固定种子价格矩阵 × 5 组 config × 4 条消费路径，
                     逐字段 ``abs=0``（float 精确相等，零容差）。闸门不可放松。
2. ``model``      —— 生产模型层：真实 ``strategy_models`` 文档跑固定窗口，
                     逐数值字段 ``rel ≤ 1e-9``（含 ``abs ≤ 1e-12`` 的零值兜底）。
3. ``regression`` —— 回归链层：``tests/regression`` 的 DIFF 集合快照，
                     门禁语义是「不允许新增红灯」（历史红灯是既有债务，已冻结）。

CLI 见 ``run_baseline.py``。本包不含生产代码，也不被 ``app/`` 反向引用。
"""

# -*- coding: utf-8 -*-
"""执行语义零漂移输入构造包（回测引擎演进 P0）.

只服务于 ``tests/test_execution_parity.py`` 与 ``tests/execution_baseline/
engine_layer.py``：构造固定种子输入、驱动现有四条消费路径、把结果归一化为
可精确 round-trip 的 JSON 结构。夹具与 CLI 统一在 ``tests/execution_baseline/``
（``engine_parity.json`` + ``run_baseline.py``），本包只剩“造输入/比字段”两件事。

本包不含任何生产代码，也不被 ``app/`` 反向引用。
"""

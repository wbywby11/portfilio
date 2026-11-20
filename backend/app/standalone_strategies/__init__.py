"""独立策略（打包形态）容器.

与 ``app/monitor/researcher_strategies/`` 同构：一个策略一个包，包内完成选样、赋权、
约束、风控，对外只暴露参数与底层资产。执行不在这里：回测走 ``CompositionPipeline``
→ ``BacktestEngine``，监控走 ``MonitorEngineAdapter`` → ``daily_stepper``，组合仍走
``portfolio_service``。

目录约定
--------
``app/standalone_strategies/<code>/``
    ``__init__.py``   导出策略类
    ``strategy.py``   策略类本体，继承 ``app.allocation.models.base.BaseStrategyModel``

边界
----
- 注册仍在 ``app/allocation/strategy_manifest.py`` 的 ``STRATEGY_MANIFEST``
  （唯一注册点），本包不建第二套 registry；
- 基类 ``BaseStrategyModel`` 留在 ``app/allocation/models/base.py``
  （三层策略与独立策略共用同一个父类）；
- 运行前数据门禁 ``app/backtesting/data_contract.py`` 属执行层，本包只调用不实现；
- 新增独立策略：在本目录建 ``<code>/strategy.py``，再在 ``STRATEGY_MANIFEST``
  加一行 ``StrategyEntry(..., strategy_form="standalone")``。模板、类路径、
  composition 全部由清单自动派生。
"""

# backtesting 计算引擎架构

> 定位声明：`app/backtesting` 是系统的**计算引擎**，"回测"只是其运行模式之一。
> 包名保留历史命名，但其职责是：为全量回测、日常监控、模拟交易、组合复合等
> 所有计算场景提供**同一份**策略计算逻辑，保证多种计算模式的结果一致。

---

## 1. 为什么是"计算引擎"而不是"回测工具"

系统中以下场景都需要"按策略模型计算逐日权重/净值"：

| 计算模式 | 入口 | 特点 |
|---|---|---|
| 全量历史回测 | `app/api/backtests.py`、`app/api/strategy_model.py` | 历史区间完整推进，可含费率/滑点 |
| 监控每日前向推演 | `app/monitor/engine_adapter.py`、`app/monitor/portfolio_backtest_monitor.py` | 增量推演、指数口径（零成本） |
| 模拟交易 | `app/portfolio/sim_trade_engine.py` | 逐日跟踪模拟持仓 |
| 组合第二段引擎运行 + 产品层 | `app/portfolio/composite_runner.run_composite_unified` + `product_layer.py` | 子策略 NAV 折算合成资产，经同一引擎逐日撮合 |

如果每种模式各自实现策略逻辑，必然产生口径漂移（同一策略在回测与监控中
结果不一致）。因此所有模式**共享本包的计算内核**，逻辑一致性由
"同一份代码"天然保证：修复一处（如调度时序、选择器口径），四种模式同时生效。

---

## 1.5 系统四层架构与模块边界

系统整体按四层组织，依赖方向单向向下：

```
应用层      FastAPI 入口 + 前端参数配置（落库留存）
            api/backtests.py、api/strategy_model.py、portfolio/*_router、monitor/*
            前端 StrategyModelForm / PortfolioCreate（ParamSchema core/advanced 分档）
            │  （允许：上层消费引擎，禁止被引擎反向依赖）
            ▼
统一引擎层  app/backtesting（本包），模式无关内核，两步计算：
            Step1 生成配置结果 —— 各调仓日目标权重快照（决策面）
            Step2 回测（历史全区间）与日常监控（样本外逐日推演），同一内核
            │
            ▼
策略层      四个并列模块（可插拔组件，统一注册）：
            selection（资产选择）/ allocation（权重分配）/ control（风险控制）/ portfolio（组合权重模型）
            具体策略 = 模块的配置实例：四象限、GMSI2、hybrid_12、sharpe_18 …
            │
            ▼
数据层      MongoDB 集合（assets / asset_prices / trade_dates / fx_rates /
            strategy_models / model_templates / backtest_records / monitor_states / portfolios …）
            治理：docs/DATA_ARCHITECTURE.md + DATA_IMPORT_SPEC.md + 审计集合
```

**模块边界要点：**

- 策略层四模块只负责"给定输入算权重/信号"，不含引擎推进、落库、API 逻辑；
- 引擎层只负责"按 spec 逐日推进与撮合"，不感知参数来源（一律经 `build_backtest_params` 组装）；
- 应用层只做编排、落库与展示，禁止复制策略/引擎逻辑。

**组合模块定位（第四策略模块）：**

组合（`app/portfolio/weight_models`）是与 selection / allocation / control 并列的
第四策略模块，负责把三个模块构建出的子策略按一定逻辑（固定权重 / 等权 /
风险平价 / 最小方差 / 四象限信号驱动）组合成完整策略。组合与三模块共用
同一计算逻辑：子策略逐日收益折算为**合成资产**价格序列
（`synthetic_feed.build_synthetic_prices`），组合权重模型经
`PortfolioWeightAllocator` 包装为引擎可识别的 allocator，交同一个
`BacktestEngine` 逐日撮合（编排入口 `app/portfolio/composite_runner.run_composite_unified`），
实现"一套引擎、两种标的"（真实资产 / 合成资产），组合层保留全部计算语义
（权重漂移开关、事件驱动再平衡、母层波动率控制、产品层叠加）。

---

## 2. 包内三层结构

### 2.1 计算内核（模式无关，纯计算）

| 文件 | 职责 |
|---|---|
| `composition_pipeline.py` | 三层编排器（Selection → Allocation → Control），实现 `IStrategy`，唯一策略逻辑真相源 |
| `composition_builder.py` | composition 装配唯一来源（所有入口统一推导，避免选择器接入不一致） |
| `strategy_api.py` | `IStrategy` 抽象接口（`generate_target_weights` / `compute_monitoring_metrics` / `get_capabilities`） |
| `engine.py` | `BacktestEngine`：逐日推进主循环（信号时点、成交时序、NAV 累计） |
| `schedule.py` | `ScheduleResolver`：信号日识别 + 执行日推算（频率/延迟/自定义信号日历） |
| `data_feed.py` | `DataFeed`：行情矩阵供给与价格日历 |
| `execution.py` | `ExecutionEngine`：目标权重 → 成交（费率/滑点可选） |
| `risk.py` | `RiskManager`：杠杆/权重上限约束 |
| `signal.py` / `types.py` / `config.py` | 信号原语、基础类型、回测配置 |
| `synthetic_feed.py` | 合成资产价格构建：子策略 NAV → 合成资产价格矩阵（组合第二段引擎运行的数据输入） |
| `runner.py` | 唯一引擎构造点：`run_unified(spec)` / `generate_targets(spec)` 两步计算入口 |

### 2.2 模式编排（产品层叠加）

| 文件 | 职责 |
|---|---|
| `product_layer.py` | 产品层：组合之上的最终产品配置（策略组合 + 短债 + 现金等） |

> 组合层的编排（合成资产 + 组合权重 allocator）位于应用层
> `app/portfolio/composite_runner`，经唯一入口 `run_unified` 调用本包内核；
> 原 NAV 级复合实现 `composite_engine.py` 已退役（差异量化见
> `docs/组合适配统一引擎双跑比对报告.md`）。

### 2.3 报告分析（形态转换，不含指标公式）

| 文件 | 职责 |
|---|---|
| `analytics.py` | 单策略报告形态转换（净值 → 指标/曲线/持仓展示结构） |
| `portfolio_analytics.py` | 组合绩效：子策略分解、收益归因、相关性 |

> 绩效指标口径（年化因子、夏普、回撤等）的**单一真相源是 `app/analysis/performance.py`**，
> 报告分析层只做委托与形态转换，禁止自行实现指标公式。

---

## 3. 依赖方向规则

```
api / services / portfolio / monitor
            │  （允许：上层消费引擎）
            ▼
      app.backtesting ──────► selection / allocation / control
      （计算引擎）              （策略三层组件，允许向下依赖）
            │
            ▼
   app.analysis.performance （绩效口径委托，允许）
```

- **允许**：上层模块（`api` / `services` / `portfolio` / `monitor`）导入 `app.backtesting`
- **允许**：`app.backtesting` 向下依赖策略三层（`selection` / `allocation` / `control`）
- **禁止**：`app.backtesting` 反向依赖 `api` / `monitor` / `portfolio` / `services`

**白名单例外（已定性，守卫测试显式放行）：**

| 例外依赖 | 限定文件 | 定性 |
|---|---|---|
| `app.analysis.performance` | `analytics.py`、`portfolio_analytics.py` | 绩效口径单一真相源，委托合理 |
| `app.services.market_service` | 仅 `data_feed.py` | 数据源获取，限定于数据供给层 |

边界由 `tests/test_backtesting_boundary.py` 静态扫描守卫（ast 解析 import），
违规即测试失败——边界从"约定"变为"机器可验证"。

---

## 4. 消费者引用现状

| 消费者 | 消费组件 | 模式 |
|---|---|---|
| `api/backtests.py` | engine / pipeline / composite_runner / analytics / product_layer 等全组件 | 回测入口编排 |
| `api/strategy_model.py` | engine / pipeline / analytics | 模型快捷回测 |
| `portfolio/portfolio_service.py` | runner / composite_runner / composition_builder | 子策略回测与组合 |
| `portfolio/sim_trade_engine.py` | pipeline / execution / composite_runner / signal | 模拟交易 |
| `portfolio/composite_runner.py` | runner / synthetic_feed / weight_models | 组合第二段引擎运行编排 |
| `monitor/engine_adapter.py` | composition_pipeline | 监控权重推演（不重写策略逻辑） |
| `monitor/portfolio_backtest_monitor.py` | composite_runner | 组合监控 |
| `monitor/researcher_strategies/base.py` | composition_pipeline | 研究员策略监测 |
| `services/backtest_analysis_service.py` | engine / pipeline / analytics | 回测分析服务 |
| `portfolio/portfolio_router.py` | portfolio_analytics | 组合报告 |

---

## 5. 明确不做（边界决策记录）

1. **不改包名**：`backtesting` 作为历史命名保留，以本文档与包级 docstring 显性化其计算引擎定位。
2. **不做 `core/modes` 物理子包拆分**：会引发全库 import 路径大改动，收益低于风险；
   分层用文档 + facade + 守卫测试表达，未来大版本可重新评估。
3. **不迁移 `analytics.py` / `portfolio_analytics.py` 至 `app/analysis`**：
   指标口径已正确委托，归属在文档层面标注为"报告分析层"即可。
4. **三处向上依赖仅定性登记，不做依赖倒置重构**：均限定于单一文件且职责正当。

---

## 6. 新增计算模式的接入约定

新增任何"按策略模型计算权重/净值"的场景时：

1. **必须**经由 `CompositionPipeline`（或其上层 `BacktestEngine`，一律经 `runner.run_unified`
   构造）获取权重，组合场景经 `app.portfolio.composite_runner`，禁止复制策略逻辑；
2. 参数一律从 DB 模型文档经 `build_backtest_params` 组装，引擎不感知参数来源；
3. 模式差异（费率、起止日、增量/全量）通过 `BacktestConfig` / 调用参数表达，
   不得在策略逻辑内部分叉；
4. 若内核能力不足（如新的调度语义），修复内核组件而非旁路实现——
   修复对所有模式同时生效正是本架构的价值所在。

---

## 7. 最终形态与端到端验证记录（P5）

### 7.1 监控 == 回测（同源不变式）

- 单策略监控经 `runner.run_unified` / `generate_targets` 同一内核推演；
  组合监控 `monitor/portfolio_backtest_monitor.run_portfolio_monitor_pipeline`
  复用 run-portfolio 端点**同一套构建块**（子策略回测 + 四象限组件 +
  `run_composite_unified` + 产品层），不另存回测记录。
- 四象限权重组件统一由 `portfolio/quadrant_components.build_quadrant_weight_components`
  组装，回测 API（`api/backtests.py`）、监控管线、`portfolio_service._run_composite`
  三方共享，消除参数断点。
- 不变式守卫：`tests/test_monitor_homology.py`（调仓日集合 / 归一 NAV /
  逐日权重 / generate_targets 快照四项一致性）。

### 7.2 策略实例的来源（前端配置，非脚本入库）

四象限、GMSI2 等具体策略都是**前端策略建模产出的配置实例**
（StrategyModelForm / PortfolioCreate → strategy_models 落库），引擎与
验收链路均只消费库内模型文档；不存在脚本式入库通道作为架构组件。

### 7.3 原型数值验收（测试侧资产）

- `tests/regression/manifests/<name>.yaml` + `tests/regression/prototype_manifest.py`：
  清单驱动的验收口径（基线 NAV、容差），仅供回归测试消费，**非系统架构组件**；
- `tests/regression/test_prototype_alignment.py`：按清单逐层跑系统回测与
  原型基线对账（GMSI2：GMAP / GCMI / 60-40 月度母组合，含母层 vol 控制口径）；
- 新增原型只需追加清单文件并在 `PROTOTYPES` 登记，模型须经前端建模入库。

## 8. 应用层分工（P6–P9 治理成果）

> 1.5 节约定"应用层只做编排、落库与展示"；本节固化 P6–P9 治理后的
> 应用层物理分工与守卫机制。

### 8.1 分层模式：路由瘦身 + 编排下沉

- **`app/api/*` 只留端点壳**：参数校验（含 `validate_object_id`）、
  依赖注入、调用编排模块、Response 包装；单文件 ≤1000 行。
- **编排模块（`app/services/*`）**：承接原路由内的编排主体，方法体平移、
  签名去 `Depends`，命名约定 `xxx_core(...)`；依赖方向只向下
  （backtesting / schemas / models / data），不 import `app.api`。
- **请求响应模型（`app/schemas/*`）**：按域归组（如 `schemas/backtests.py`），
  路由文件不再内联大段 Pydantic 模型。
- 治理成果：`api/backtests.py` 2337→722 行（编排迁
  `services/backtest_orchestration.py`）；`api/strategy_model.py` 1199→917 行
  （监控/权重变化迁 `services/strategy_model_monitoring.py`）；
  `api/asset.py` 1144→927 行（模板生成迁 `services/price_templates.py`、
  Excel 导入编排迁 `services/price_import_flow.py`）。

### 8.2 行情读收口（PriceRepository）

- `app/data/price_repository.py`：asset_prices 集合读端唯一收口
  （`get_price_docs` / `get_price_dataframe` / `get_latest_price_date(s)`），
  依赖注入 db、只读不写；`asset_service` 价格查询委托之，`MarketService`
  经 AssetService 间接消费。
- 豁免：行情导入引擎（`price_importer.py`，读写耦合）、
  `monitor/data_provider.py`（监控专属代码映射）、导入写路径、regression fixture。

### 8.3 期权定价模块分工

`app/options/core.py`（原 2161 行）按职责拆为三模块，core.py 保留兼容再导出层
（dispatcher.py 与 scripts 的既有导入面不变）：

| 模块 | 职责 |
|---|---|
| `pricing_vanilla.py` | 折现/远期工具、MarketParams/PricingResult、欧式香草/价差/二元/单障碍/固收 |
| `pricing_exotic.py` | 雪球/凤凰/双鲨/亚式/彩虹/区间累积/可赎回固收/数字区间 |
| `pricing_numeric.py` | 二叉树（美式）/有限差分（PDE）/SABR/Dupire 局部波动率 |

### 8.4 架构守卫（tests/test_architecture_guard.py）

1. **行数预算**：api/services 单文件 ≤1000 行；超标须登记限期治理白名单，
   治理完成后测试强制移出（当前仅余 `services/monitor_service.py`）；
2. **依赖方向**：复用 `tests/test_backtesting_boundary.py`，
   backtesting 禁止反向依赖上层；
3. **行情读收口**：api/services/portfolio/backtesting 禁止对行情集合裸
   `find/aggregate`，必须经 PriceRepository；
4. **路由面契约**：全量 method+path 与 `tests/_routes_baseline.txt` 快照一致，
   任何端点变化必须与前端协同确认（合法新增时重新生成基线）。

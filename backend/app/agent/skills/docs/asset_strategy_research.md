---
name: asset_strategy_research
display_name: 资产与策略研究
description: 面向大类资产配置与ETF策略的端到端研究工作流，覆盖策略推荐、模型创建、回测分析、权重计算与组合构建
version: "1.0"
tags:
  - 策略
  - 回测
  - 资产配置
  - ETF
  - 组合
trigger_keywords:
  - 推荐策略
  - 策略推荐
  - 配置策略
  - 策略对比
  - 对比策略
  - 大类资产配置
  - 风险平价
  - 均值方差
  - 风险预算
  - ETF轮动
  - ETF策略
  - 跑一下回测
  - 执行回测
  - 策略回测
  - 组合构建
  - 创建组合
  - 模拟组合
  - 调仓历史
  - 资产研究
  - 生成报告
  - 策略研究报告
  - 总结报告
  - 保存模型
  - 保存策略
  - 入库
  - 创建模型
  - 保存当前结果
  - 保存最优
exclude_keywords:
  - 信用
  - 评级
  - 报告
  - 导出
  - 资产选择
  - 动量筛选
  - 波动率监测
  - 波动率告警
toolset:
  - asset_research
  - report
show_plan: false
steps:
  - name: 资产识别
    description: 用户给出资产名称时，先查询系统资产代码
    tools:
      - query_assets
    skip_if: 用户已直接提供资产代码
  - name: 开放式推荐
    description: 用户未指定具体策略类型时，基于资产特征推荐候选策略
    tools:
      - recommend_strategy
    condition: 用户提出"帮我配置/推荐策略"等开放需求
    skip_if: 用户已明确指定策略类型
  - name: 多策略对比回测
    description: 对推荐或用户指定的候选策略批量回测对比
    tools:
      - compare_strategies
    condition: 存在2个及以上候选策略
  - name: 单策略回测
    description: 对最终选定的策略执行详细回测，返回净值/权重/波动率三图
    tools:
      - execute_backtest
  - name: 权重计算（可选）
    description: 对最优策略计算具体权重分配
    tools:
      - compute_weights
    skip_if: 回测结果已包含末日权重
  - name: 策略模型保存
    description: 将策略配置保存为模型供后续复用。对比完成后主动询问用户是否需要保存最优策略。
    tools:
      - create_strategy_model
    condition: 用户说"保存""入库""创建模型""保存最优"，或对比完成后用户确认保存
  - name: 组合构建（可选）
    description: 基于策略模型创建模拟组合，追溯历史业绩
    tools:
      - create_portfolio
    condition: 用户明确表示需要创建组合 / 跟踪模拟盘
  - name: 策略研究报告生成（可选）
    description: 将完整研究过程生成为结构化报告，保存到报告中心
    tools:
      - generate_strategy_report
    condition: 用户明确要求生成报告 / 总结 / 导出研究过程
---

## 资产与策略研究工作流指导

### 工作流总纲

本 Skill 覆盖"从需求到可执行配置"的全链路：**资产识别 → 策略选择 → 回测对比 → 组合落地**。按用户诉求灵活跳过非必要步骤，但回测与三图展示是绝大多数诉求的核心环节，不要省略。

### 判断用户诉求类型

1. **开放式需求**（关键词：推荐、帮我配置、什么策略好）
   - 执行完整流程：query_assets → recommend_strategy → compare_strategies → execute_backtest（对最优）→ 可选 compute_weights
2. **明确指定策略**（关键词：做风险平价、跑均值方差、用 ETF 轮动）
   - 跳过 recommend_strategy，直接 query_assets（如需）→ execute_backtest 或 create_strategy_model + execute_backtest
3. **策略对比需求**（关键词：对比、哪个更好、A 和 B 谁强）
   - 直接 query_assets → compare_strategies → 输出 comparison_table
4. **单次截面权重**（关键词：现在该买什么、今日权重、目标仓位）
   - query_assets → compute_weights
5. **组合管理需求**（关键词：创建组合、看看我的组合、调仓历史）
   - create_portfolio / get_portfolio / get_rebalance_history / execute_rebalance
6. **研究报告需求**（关键词：生成报告、总结研究、导出报告）
   - 在完成策略研究流程后，调用 generate_strategy_report 自动从对话历史提取数据生成报告
   - 报告保存到报告中心，可在报告列表中查看和下载

### 策略选择速查

| 适用场景 | 推荐策略 | template_code |
|----------|----------|---------------|
| 多资产分散，无明显预期收益 | 风险平价 | `risk_parity` |
| 追求夏普最大化 | 协方差-夏普优化 | `cso` |
| 稳健组合，限定目标波动 | 风险预算-目标波动率 | `risk_budget_target_vol` |
| 历史数据充足，追求有效前沿 | 均值方差 | `mean_variance` |
| 人工指定权重 | 主观配置 | `manual_allocation` |
| 10+ 只 ETF 轮动 | ETF 周期轮动 | `etf_cycle_rotation` |

ETF 周期轮动需指定 `sub_strategy` 参数：`volatility`（波动率）/ `return_deviation`（收益+乖离率）/ `hybrid`（混合因子）/ `breakout`（强势突破）。

### 回测默认参数

- 起止日期：未指定时默认回测区间为**近3年**，`end_date = 今天`，`start_date = 今天 - 3年`
- 初始资金：1000万（10_000_000）
- 调仓频率：`月`（monthly）
- `lookback_days`：500 天（策略内部可按需使用）

### 回测三图说明

`execute_backtest` 返回结果自带以下三张图，文字回复**不要复述图表数值**：
1. **净值曲线**：单位净值时序（折线图）
2. **持仓权重变化**：各资产权重随时间的堆叠面积图
3. **滚动波动率监控**：组合年化波动率时序（折线图）

> 这是**回测结果的一部分**，与独立的"波动率监测模块"不等同。该图可直接展示，无需用户额外确认。

### 策略对比输出规范

`compare_strategies` 返回的 `comparison_table` 必须**完整展示在回复最开始**（Markdown 表格），然后再给出简要结论（不超过 3 行）。图表自动展示，无需描述图表内容。

> **对比完成后的保存指引**：`compare_strategies` 返回结果包含 `best_strategy` 字段，标识了综合表现最优的策略。在展示对比结果后，主动询问用户是否需要保存最优策略为模型。用户确认后，从对比结果中提取 `best_strategy.strategy_type`、`asset_codes` 等参数，调用 `create_strategy_model` 完成保存。

## 策略研究报告生成

当用户明确要求"生成报告"、"总结研究过程"、"导出策略研究报告"时，调用 `generate_strategy_report` 工具：
- 工具会自动从当前对话历史中提取所有工具调用结果（资产查询、策略对比、回测数据、权重计算等）
- 生成结构化的单一策略研究报告，包含七大章节
- 报告保存到报告中心，支持 Markdown 下载
- **数据准确性**：报告中所有数据均来自工具调用结果，不包含任何虚构内容
- 未在用户要求时不主动调用此工具

### 按需启用模块（重要约束）

- **资产选择模块**（`app/selection/`）和**波动率监测模块**（`app/monitor/`）为独立业务模块，**不通过本 Skill 调用**。
- 只有当用户明确提及以下关键词时才谈及这些模块：
  - 资产选择："动量筛选"、"选资产"、"资产池筛选"
  - 波动率监测："波动率监测"、"波动率告警"、"实盘监控"
- 不要主动向用户提出"是否需要开启资产选择"、"是否配置波动率告警"等引导性问题。

### 数值精度规范

- 收益率/波动率（%）：保留 2 位小数
- 夏普比率 / Calmar：保留 2-3 位小数
- 权重（%）：保留 2 位小数
- 金额：千位分隔，保留 2 位小数

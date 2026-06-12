# data_hub 三表 · L1-L5 典型场景问答清单

> **数据基础**（实测于 2026-06-09，连接 `mongodb://localhost:27017/asset_allocation`）
> - `subject_risk_records` — 主体观点风险记录表，**40 条**，18 个独立主体
> - `zysc_ptl_info_records` — 产品信息记录表，**35 条**，全部由"浙银理财"管理
> - `zysc_ptl_holder_records` — 产品持有人汇总记录表，**175 条**（35 产品 × 5 期）
>
> **画像层级**：L1 单表静态 / L2 域内 / L3 跨域 / L4 共振 / L5 字段统计

---

## 数据全貌速览

### subject_risk_records 实测分布

| 维度 | 分布 |
|------|------|
| 风险等级 | 黄 20 (50%) / 高 12 (30%) / 低 8 (20%) |
| 省份 | 广东省 23 / 北京市 10 / 上海市 3 / 江苏省 2 / 浙江省 2 |
| 行业 | 房地产业-房地产开发经营 14 / 建筑业-土木工程建筑业 6 / 金融业-货币金融服务 6 / 信息传输与软件 6 / 金融业-资本市场服务 4 / 制造业-汽车制造业 2 / 金融业-保险业 2 |
| 企业性质 | 国有企业 21 (53%) / 民营企业 14 (35%) / 混合所有制 5 (12%) |
| 规则大类 | 客户经营情况 14 / 客户财务情况 9 / 客户融资情况 6 / 客户舆情情况 4 / 客户信用情况 4 / 客户合规情况 3 |
| Top 主体 | 中国恒大集团 3 / 万科企业 3 / 绿地控股 3 / 碧桂园控股 3 / 中国平安 2 / 华为 2 / 阿里巴巴 2 |

### zysc_ptl_info_records 实测分布

| 维度 | 分布 |
|------|------|
| 风险等级 | R3 22 (63%) / R4 6 (17%) / R2 5 (14%) / R1 2 (6%) |
| 策略类型 | FOF配置 9 / CTA趋势 8 / 混合策略 5 / 纯债策略 4 / 指数增强 4 / QDII海外 3 / 固收+ 2 |
| 管理人 | 浙银理财 35（100%） |

### zysc_ptl_holder_records 实测分布

| 报告期 | 记录数 |
|--------|--------|
| 2025-06-30 | 35 |
| 2025-12-31 | 35 |
| 2026-03-31 | 35 |
| 2026-06-30 | 35 |
| 2026-09-30 | 35 |

最新期前十集中度 Top5：PTL_014 (90.0%)、PTL_003 (90.0%)、PTL_007 (84.8%)、PTL_015 (77.6%)、PTL_050 (73.1%)

---

## L1 单表静态画像 — 字段语义、分布、异常

> **使用场景**：回答"这张表/这个字段是什么"。**仅查单张表**，引用 L1 的 `distribution` 字段作答。

| ID | 典型问题 | 命中表 | 回答要点 |
|----|---------|-------|---------|
| **L1-Q1** | 主体风险表里风险等级有哪几档？分布如何？ | subject_risk_records | 三档：黄(20)/高(12)/低(8)，黄色关注级 50% 占主导；**注意字段值是"高"而非"高风险"** |
| **L1-Q2** | 产品信息表的风险等级是怎么编码的？哪一档产品最多？ | zysc_ptl_info_records | R1-R4 四档，R3 平衡型 22 个(63%)最多，无 R5；策略以 FOF配置(9) 和 CTA趋势(8) 为主 |
| **L1-Q3** | 持有人表的份额字段有哪几个？前十份额跟个人+机构是什么关系？ | zysc_ptl_holder_records | 前十/个人/机构三个**独立口径**——前十 = Top10 持有人合计，个人+机构 = 投资者类型合计；**前十 ≠ 个人+机构** |
| **L1-Q4** | subject_risk_records 的 rule_large 大类有几种？哪些场景常触发？ | subject_risk_records | 6 类（经营 14、财务 9、融资 6、信用 4、舆情 4、合规 3）；房地产+经营恶化是最高频组合 |
| **L1-Q5** | 持有人数据有几个报告期？跨期间隔多久？ | zysc_ptl_holder_records | 5 期（2025-06-30 / 2025-12-31 / 2026-03-31 / 2026-06-30 / 2026-09-30），半年→季度间隔 |
| **L1-Q6** | 产品代码 PTL_007 的全部基础信息 | zysc_ptl_info_records | 单条记录 + 全部 52 个字段说明 |
| **L1-Q7** | 风险信号描述里出现频率最高的关键词是什么？ | subject_risk_records | 基于 signal_dascribe 字段做词频统计；房地产高风险记录中"债务""违约""偿付"高频 |

**推荐工具**：`semantic_profile(operation='table_profile')` 或 `smart_table_router(top_k=3, top_k_views=0)`

---

## L2 域内画像 — 域内多表协同、一致性、孤儿检测

> **使用场景**：回答"接入域整体如何/导入是否健康/表之间能否关联"。**同时查 records + batches + info + holder**。

| ID | 典型问题 | 涉及表 | 回答要点 |
|----|---------|-------|---------|
| **L2-Q1** | data_hub 域里数据完整性有哪些孤儿/异常？ | 6 张表 | subject_risk 有 1 个孤儿 batch、zysc_ptl_info 有 1 个孤儿 batch、zysc_ptl_holder 完全匹配 |
| **L2-Q2** | 最近的导入批次成功率怎么样？哪类数据失败最多？ | 3 张 batches 表 | 12 批：success 7 / partial 3 / failed_upstream 2；failed 集中在 subject_risk 接口 |
| **L2-Q3** | 持有人数据的 175 条与产品信息表的 35 条产品代码是否完全对得上？ | holder + info | 是，35 产品 × 5 期=175，产品代码 100% 匹配 |
| **L2-Q4** | 这个域里能直接关联的连接键有哪些？ | 3 表 | `_batch_id`（records→batches 溯源）、`产品代码`（info ↔ holder 主键）、`subject_name`（risk ↔ ISR 语义键） |
| **L2-Q5** | partial 状态的批次是怎么产生的？有没有数据丢失？ | batches | partial 通常因上游 pageMsg 限制截断，需对照 total_returned vs inserted+updated 排查 |
| **L2-Q6** | data_hub 域的 6 张表里有哪些是"业务记录表"哪些是"批次审计表"？ | 6 张表 | 3 records + 3 batches 双表配对结构，通过 `_batch_id` 一对多关联 |

**推荐工具**：`smart_auto_analyze(view_id='datahub_s4_import_audit')` 自动执行场景视图

---

## L3 跨域画像 — 多个域之间的穿透链路

> **使用场景**：用户问句含"穿透/关联/影响/对得上"等词，必须用 L3 的 `join_path` 作为穿透依据。data_hub 涉及的 L3 画像有 2 个：
> - `datahub_risk_subject`（外部风险 → 主体 → 产品 穿透）
> - `datahub_product_bridge`（外部产品 → 内部产品 桥接）

| ID | 典型问题 | 跨越的域 | 回答要点 |
|----|---------|---------|---------|
| **L3-Q1** | subject_risk_records 中的高风险主体，在主体域 dwd_isr_institution 里能完全对得上吗？ | data_hub × subject | 18 个独立 subject_name 与 dwd_isr_institution 的 18 个 ISR_NM 完全语义匹配；穿透键为 subject_name=ISR_NM |
| **L3-Q2** | 外部产品表 zysc_ptl_info_records 的 35 个产品，在内部产品域 dwd_ptl_info 里都有对应吗？ | data_hub × product | 100% 匹配（外部.产品代码 = 内部.PORT_ID）；可通过 `domain_query(action='join')` 桥接 |
| **L3-Q3** | 高风险的房地产企业（万科/碧桂园/恒大）在持仓表里发的债有多少敞口？ | data_hub × subject × asset × product | 穿透：subject_risk → ISR_ID → dwd_ast_info（按 ISR_ID 过滤） → dwd_ptl_ast_hld；得到组合穿透敞口 |
| **L3-Q4** | 外部产品的 35 个理财，与内部产品域的 50 条产品有多少重叠？多出来的是什么？ | data_hub × product | 35 个外部产品全部在内部 50 条中，多出 15 个为内部独立创建产品（如 FOF 母产品） |
| **L3-Q5** | 一个 subject_name 触发风险后，到组合敞口的影响路径是什么？ | 4 域穿透 | risk → subject → ast → ptl，关键中转表是 dwd_isr_institution.ISR_ID（连接外部主体名 → 内部资产代码） |

**推荐工具**：`smart_table_router(top_k_views=3)` 看 L3 画像 + `domain_query(action='join')` 执行穿透

---

## L4 共振/传染画像 — 多域因果传导链与预警

> **使用场景**：用户问句含"传染/共振/连锁/前兆"等词。data_hub 涉及的 L4 画像有 2 个：
> - `datahub_risk_resonance`（外部风险与内部评级双源共振）
> - `datahub_dataflow_crisis`（数据断流与估值链断裂）

| ID | 典型问题 | 共振路径 | 回答要点 |
|----|---------|---------|---------|
| **L4-Q1** | 外部风险信号和内部评级如果一起恶化，会怎么传染到组合？ | data_hub → risk → subject → asset → valuation | ① 外部风险信号升级 → ② 触发内部评级关注 → ③ 关联资产估值下调 → ④ 组合 NAV 受损；预警阈值：单主体 7 日内 ≥3 条高风险 + 内部评级降 1 档 |
| **L4-Q2** | subject_risk 接口断流后，对内部估值有什么影响？ | data_hub → product → valuation → market | failed_upstream 持续 ≥3 天 → 风险信号缺失 → 关联产品估值无及时修正 → 组合公允价值偏离实际市场 |
| **L4-Q3** | 高风险主体扎堆出现在房地产业，与组合的房地产敞口有共振风险吗？ | data_hub.risk × asset.industry × ptl.holding | 14 条房地产风险 + 组合中房地产敞口 → 触发 L4 信用传染场景：单点违约 → 担保链 → 关联方 → 同行业利差走阔 |
| **L4-Q4** | partial 状态的 zysc_ptl_info 批次是数据断流前兆吗？ | data_hub.batches × valuation | partial 表明上游 pageMsg 截断，若连续 3 批 partial 则可能漏接产品 → 内部 ptl_info 不完整 → 估值流水链断裂 |
| **L4-Q5** | 外部风险数据延迟，内部还能及时识别系统性风险吗？ | data_hub × risk × subject | 不能完全替代 — 外部 subject_risk_records 是早 7-14 天的舆情前哨，断流期需 fallback 到内部 dwd_isr_sentiment 84 条舆情 |

**推荐工具**：`semantic_profile(operation='resonance')` 查看共振链 + `warning_indicators` 清单

---

## L5 字段统计画像 — 动态统计、异常告警、阈值偏离

> **使用场景**：用户问句含"当前/最近/偏离/异常/阈值"等词。⚠️ 当前 data_hub 仅有 1 条 L5 记录，建议执行 `python scripts/generate_datahub_l5_profiles.py --apply` 补齐三表的字段级统计。

| ID | 典型问题 | 字段级统计 | 回答要点（基于实际数据） |
|----|---------|-----------|-----------|
| **L5-Q1** | subject_risk_records 的 risk_signal_level 当前分布偏离正常基线吗？ | 字段：risk_signal_level | 当前 黄/高/低 = 50%/30%/20%，对照 L1 基线（黄占主导符合常态）；**高风险 30% 已偏高**，正常应 ≤20% |
| **L5-Q2** | 持有人前十份额这个字段近 5 期均值有什么变化？ | 字段：前十份额 | 5 期均值漂移：14.5 → 14.6 → 14.7 → 14.8 → 14.9 亿，缓慢上升 2.8%（机构化趋势）；标准差 8.2 亿稳定 |
| **L5-Q3** | 机构占比这个衍生指标的跨期漂移最大值是多少？ | 衍生：机构份额/(机构+个人) | 平均漂移 ±0.7%，最大 +25%（PTL_007）；R4 高风险产品漂移更大 |
| **L5-Q4** | 产品风险等级的众数是 R3，但有偏离 R3 的异常产品吗？ | 字段：风险等级 | R3 占 63% 为众数；R4 占 17%（6 个）为偏离区，需关注其策略类型/估值方法是否匹配 |
| **L5-Q5** | rule_large 字段中各类的占比有没有明显失衡？ | 字段：rule_large | 客户经营 35% > 客户财务 22.5% > 客户融资 15%；客户合规仅 7.5%（最低），可能上游分类规则未触发 |
| **L5-Q6** | subject_name 字段的 cardinality 怎么样？是否符合多对一的预期？ | 字段：subject_name | 18 个 distinct values / 40 条记录 = 平均 2.2 条/主体，恒大/万科/碧桂园/绿地各 3 条最高（符合多事件聚集预期） |
| **L5-Q7** | 产品代码字段的 holder/info 关联完整性是多少？ | 衍生：cross-table referential integrity | 100%（35 个产品代码 × 5 期 = 175 条 holder 全部命中 35 条 info 主键） |

**推荐工具**：`semantic_profile(operation='stats_profile', target='表名')` 查看字段统计 + `raw_stats`

---

## LLM 路由匹配建议

下表给出**典型问句 → 优先调用工具**的对应关系，可作为系统提示词补充：

| 问句包含 | 推荐工具 / 路径 |
|---------|----------------|
| "字段/分布/最多" → 单表元数据 | `semantic_profile(operation='table_profile')` 或 `smart_table_router(top_k=3, top_k_views=0)` |
| "孤儿/批次/导入" → 域内审计 | `smart_auto_analyze(view_id='datahub_s4_import_audit')` |
| "穿透/对得上/关联" → 跨域 | `smart_table_router(top_k_views=3)` 看 L3 画像 + `domain_query(action='join')` |
| "共振/传染/连锁" → 多域因果 | `semantic_profile(operation='resonance')` 看 L4 |
| "当前/异常/偏离/阈值" → 字段统计 | `semantic_profile(operation='stats_profile', target='表名')` 看 L5 |
| "全景/扫描/变迁/审计/交叉/预警" → 多维分析 | `smart_auto_analyze(mode='auto')` 自动选场景视图 S1-S5 |

---

## 血缘溯源约束（强制规则）

每次工具调用必须返回 `_lineage_meta`，并在最终回复最开头标注数据来源标签：

```
【数据来源】域: 通用数据接入域(data_hub) · 主体域(subject) | 表: 主体观点风险记录(subject_risk_records) · 机构主表(dwd_isr_institution)
【激活视图】高风险主体全景扫描(datahub_s1_high_risk_scan)
```

`_lineage_meta` 必含字段：

| 字段 | 说明 |
|------|------|
| `tables_used` | 实际访问的表名列表（含 join 中的右表） |
| `domains_involved` | 涉及的域代码列表 |
| `fields_accessed` | `{表名: [字段名列表]}` |
| `views_referenced` | `[{view_id, view_type, view_name}]`（如使用了视图） |
| `join_path` | 多表关联路径（如有） |
| `records_returned` | 实际返回记录数 |
| `total_in_collection` | 库内总记录数（区分于查询结果数，**反幻觉**） |
| `query_operation` | 工具操作名 |

---

## 推荐补强动作

1. **补全 L5 数据**：当前 data_hub 仅有 1 条 L5 记录，建议执行 `python scripts/generate_datahub_l5_profiles.py --apply` 覆盖三表字段级统计
2. **补强 L4 链路**：L4-Q3 涉及房地产共振，可考虑新增专门的 `real_estate_resonance` 画像
3. **L3 自动 join**：L3-Q3/Q5 类穿透问题可在 `smart_auto_analyze` 中新增 `mode='cross_domain'` 自动执行 `join_path`
4. **血缘溯源 100% 覆盖**：扫描所有工具，确保每次调用都返回 `_lineage_meta`

---

*文档版本：v1.0*
*生成时间：2026-06-09*
*数据源：MongoDB asset_allocation 库（实测）*

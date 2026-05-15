/**
 * 智能匹配 / Auto：理财产品快捷问法（与 creditRatingQuickAddons 结构一致）
 */

const PRODUCT_HUB_PREAMBLE = `【产品数据与工具（必读）】
- 允许工具内优先 **product_hub_query**（连接器 **zysc_dwd_ptl_info** 对应 Mongo **zysc_ptl_info_records**；持有人汇总为 **zysc_dwd_ptl_holder_summary**），必要时配合 **data_query**。
- **控量**：单次 **product_hub_query** 的 **limit** 建议 **≤30**（列表/探索不超过 50）；工具返回为**精简列**；需要更多列、聚合、TopN 时用 **data_query** 对 **zysc_ptl_info_records** 指定 **fields**（projection）、**limit**，或用 **aggregate**（$group/$sort + **$limit**），**禁止**一次拉全表或几十列原样灌给模型。
- **避免重复上游 / 上游不可用时**：**上游 502 或仅需读本地已入库数据时**，**product_hub_query 应设 skip_upstream_sync=true**，直接查 **zysc_ptl_info_records**；同一会话内后续提问亦建议 **skip_upstream_sync=true**（或依赖后端「每会话每 connector 仅同步一次」）；仅当用户明确要求刷新时再 **force_upstream_sync=true**。
- 已知 **产品代码** 时务必传 **prod_code**；名称/简称模糊用 **keyword**。
- 引用 **合约基准** 时注意工具返回可能为 **合约基准上限/下限/平均**（库内或仍有 **合约基准_上限** 等写法，以工具键名为准）。

`

const PRODUCT_OVERVIEW_REPORT_ADDON = `用户需要**理财产品的整体概况信息**（已入库产品的结构/规模/抽样，非单只穿透），用于经营或投研扫一眼全局。

**必须调用的工具链（缺一不可用文字冒充）**
1. **product_hub_query**：connector_id=\`zysc_dwd_ptl_info\`，**limit** 25～30；**上游不可用或仅查本地库时必须 skip_upstream_sync=true**（避免 502 重试）；本会话已同步过该 connector 时亦优先 **skip_upstream_sync=true**。本轮输出中须出现真实 **<tool_call>**。
2. **data_query**：在集合 **zysc_ptl_info_records** 上补**轻量聚合**（**aggregate**），例如：总条数 $count；或按 **产品系列** $group 计数并 **$sort** + **$limit**（如 Top 15）；可选按 **产品性质/估值方法** 分组计数；管道末端必须 **$limit**，**禁止**全表导出。
3. 若需持有人维度兜底且与概况相关：可额外 **product_hub_query**（\`zysc_dwd_ptl_holder_summary\`，小 limit + **skip_upstream_sync=true**），**勿**重复无谓上游。

**报告结构（Markdown）**
- **数据范围与口径**：工具调用说明、是否仅本地快照、Hub 同步提示（来自工具 summary/upstream_sync）。
- **规模与结构**：aggregate 的总条数/系列分布（表）；**抽样列表**：Hub 返回中的若干条（代码、简称、到期、合约基准上下限/平均若有）。
- **期限与基准导读**：基于样本与聚合的简要归纳，**禁止编造**未返回统计值。
- **局限与下一步**：本地无数据、字段缺失或截断时明确写出。

全文简洁，表格为主；单条详情勿展开过长。`

/** 智能匹配场景唯一保留的理财产品快捷项 */
export const PRODUCT_OVERVIEW_QUICK_TASK = {
  message: '理财产品的整体概况信息',
  system_turn_addon: PRODUCT_HUB_PREAMBLE + PRODUCT_OVERVIEW_REPORT_ADDON
}

/** @deprecated 请用 PRODUCT_OVERVIEW_QUICK_TASK；保留数组形式以免旧引用报错 */
export const PRODUCT_INFO_AUTO_QUICK_TASKS = [PRODUCT_OVERVIEW_QUICK_TASK]

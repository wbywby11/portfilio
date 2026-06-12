# {{ report_title | default("单一策略研究报告") }}

**研究日期**: {{ report_date | default("—") }}  
**研究资产**: {{ asset_names | default("—") }}  
**最终推荐策略**: {{ recommended_strategy | default("—") }}

---

## 一、研究背景与目标

{{ research_background | default("[待填充]") }}

### 研究资产列表

{{ asset_list_table | default("[待填充]") }}

---

## 二、初始策略配置

{{ initial_config | default("[待填充]") }}

### 候选策略列表

{{ candidate_strategies | default("[待填充]") }}

---

## 三、多模型对比分析结果

{{ comparison_table | default("[待填充]") }}

{{ comparison_conclusion | default("") }}

---

## 四、底层资产调整过程

{{ asset_adjustment | default("[本次研究未执行此步骤]") }}

---

## 五、调整后策略对比结果

{{ adjusted_comparison | default("[本次研究未执行此步骤]") }}

---

## 六、最终策略推荐与权重分配

### 推荐策略

{{ final_recommendation | default("[待填充]") }}

### 权重分配方案

{{ weight_allocation | default("[待填充]") }}

---

## 七、关键指标汇总

{{ metrics_summary_table | default("[待填充]") }}

---

**报告生成方式**: 基于对话历史自动提取  
**数据来源**: 系统内部工具调用结果  
**编制时间**: {{ generated_at | default("—") }}

# {{ report_title | default("投资决策报告") }}

**投资标的**: {{ target_name | default("—") }}  
**决策日期**: {{ decision_date | default("—") }}  
**决策类型**: {{ decision_type | default("—") }}  
**产品名称**: {{ product_name | default("—") }}  
**报告编号**: {{ report_id | default("—") }}

---

## 一、投资背景

{{ investment_background | default("[待填充] 请提供投资决策的背景及目标。") }}

### 投资目标

{{ investment_objectives | default("[待填充]") }}

---

## 二、标的研究

{{ target_research | default("[待填充] 请提供对投资标的的核心研究结论。") }}

### 核心看点

{{ key_highlights | default("[待填充]") }}

---

## 三、策略方案

{{ strategy_proposal | default("[待填充] 请提供具体投资策略方案。") }}

### 方案要素

| 要素 | 内容 |
|------|------|
| 投资金额 | {{ investment_amount | default("—") }} |
| 投资期限 | {{ investment_horizon | default("—") }} |
| 目标收益率 | {{ target_return | default("—") }} |
| 风险预算 | {{ risk_budget | default("—") }} |
| 退出机制 | {{ exit_strategy | default("—") }} |

---

## 四、收益与风险评估

### 4.1 收益预测

{{ return_forecast | default("[待填充] 请提供收益预测及情景分析。") }}

### 4.2 风险分析

{{ risk_analysis | default("[待填充] 请提供主要风险及应对措施。") }}

### 4.3 压力测试

{{ stress_test | default("[待填充] 请提供压力测试结论。") }}

---

## 五、合规审查

{{ compliance_review | default("[待填充] 请提供合规性审查结论。") }}

---

## 六、决策建议

{{ recommendation | default("[待填充] 请提供明确的投资决策建议及理由。") }}

### 决策选项

{{ decision_options | default("[待填充]") }}

---

## 七、附件

{{ attachments | default("[待填充] 相关支持材料清单。") }}

---

**投资经理**: {{ investment_manager | default("—") }}  
**研究支持**: {{ research_support | default("—") }}  
**风控意见**: {{ risk_control_opinion | default("—") }}  
**审批状态**: {{ approval_status | default("待审批") }}

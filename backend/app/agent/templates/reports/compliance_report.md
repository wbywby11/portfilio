# {{ report_title | default("合规检查报告") }}

**检查对象**: {{ inspection_target | default("—") }}  
**检查期间**: {{ start_date | default("—") }} 至 {{ end_date | default("—") }}  
**检查日期**: {{ report_date | default("—") }}  
**检查人员**: {{ inspector | default("—") }}  
**报告编号**: {{ report_id | default("—") }}

---

## 一、检查概述

{{ inspection_overview | default("[待填充] 请提供本次合规检查的概述，包括检查目的、范围、方法等。") }}

### 检查范围

{{ inspection_scope | default("[待填充]") }}

---

## 二、合规制度执行情况

{{ compliance_execution | default("[待填充] 请提供各项合规制度的执行情况。") }}

### 2.1 投资合规

{{ investment_compliance | default("[待填充] 投资范围、比例限制、关联交易等合规检查。") }}

### 2.2 信息披露合规

{{ disclosure_compliance | default("[待填充] 信息披露及时性、准确性、完整性检查。") }}

### 2.3 销售合规

{{ sales_compliance | default("[待填充] 销售适当性、宣传材料、客户资质等检查。") }}

---

## 三、检查发现

{{ findings | default("[待填充] 请列出检查发现的问题及事实描述。") }}

### 问题清单

{{ issues_list | default("[待填充]") }}

---

## 四、风险评估

{{ risk_evaluation | default("[待填充] 请提供检查发现问题的风险等级评估。") }}

### 风险分类

| 问题编号 | 问题描述 | 风险等级 | 整改期限 |
|----------|----------|----------|----------|
{% for issue in issues | default([]) %}
| {{ issue.id | default("—") }} | {{ issue.description | default("—") }} | {{ issue.risk_level | default("—") }} | {{ issue.deadline | default("—") }} |
{% else %}
| — | — | — | — |
{% endfor %}

---

## 五、整改建议

{{ remediation_suggestions | default("[待填充] 请提供针对发现问题的整改建议。") }}

### 整改措施

{{ remediation_actions | default("[待填充]") }}

---

## 六、结论与意见

{{ conclusion | default("[待填充] 请提供合规检查总体结论。") }}

---

## 七、附件

{{ attachments | default("[待填充] 检查工作底稿及相关支持文件清单。") }}

---

**检查人员**: {{ inspector | default("—") }}  
**复核人员**: {{ reviewer | default("—") }}  
**合规负责人**: {{ compliance_officer | default("—") }}  
**报告日期**: {{ report_date | default("—") }}  
**保密级别**: {{ confidentiality | default("内部机密") }}

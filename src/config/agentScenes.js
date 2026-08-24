/**
 * 数智平台AI助手 — 场景配置
 * 每个场景定义了 key、标签、图标、颜色、描述及对应 toolset
 * 快捷问题（quickQuestions）暂未定义，待明确各场景的高频需求后再补充
 */

export const AGENT_SCENES = [
  {
    key: 'auto',
    label: '智能匹配',
    icon: 'el-icon-magic-stick',
    color: '#409EFF',
    description: 'AI 自动识别您的需求，匹配最佳业务场景'
  },
  {
    key: 'data_analysis',
    label: '数据分析',
    icon: 'el-icon-data-analysis',
    color: '#67C23A',
    description: '数据资产管理、数据查询问数、统计分析、数据加工与可视化',
    toolset: 'data_analysis'
  },
  {
    key: 'report_writing',
    label: '报告写作',
    icon: 'el-icon-document',
    color: '#F56C6C',
    description: '知识库检索、报告模板生成、合规审查、导出（即将上线）',
    disabled: true,
    toolset: 'report'
  },
  {
    key: 'asset_research',
    label: '大类资产研究',
    icon: 'el-icon-s-data',
    color: '#409EFF',
    description: '资产配置策略、回测分析、组合构建、相关性/绩效研究',
    toolset: 'asset_research'
  },
  {
    key: 'enterprise_data_qa',
    label: '企业数据问答',
    icon: 'el-icon-office-building',
    color: '#909399',
    description: '主体风险舆情处罚、产品与持有人等业务库数据检索与答疑',
    toolset: 'enterprise_data_qa'
  },
  {
    key: 'credit_rating',
    label: '信用评级',
    icon: 'el-icon-trophy',
    color: '#E6A23C',
    description: '基于已入库数据的信用与主体风险辅助分析（通用查询+主体舆情风险；无独立外部评级评分引擎）',
    toolset: 'credit'
  }
]

/**
 * 根据 key 快速查找场景配置
 * @param {string} key 场景 key
 * @returns {object|undefined} 场景对象
 */
export function getSceneByKey(key) {
  return AGENT_SCENES.find(s => s.key === key)
}

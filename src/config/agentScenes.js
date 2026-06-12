/**
 * 数智平台AI助手 — 场景配置
 * 每个场景定义了 key、标签、图标、颜色、描述、快捷问题及对应 toolset
 */
import { CREDIT_RATING_QUICK_TASKS } from '@/config/creditRatingQuickAddons'
import { PRODUCT_OVERVIEW_QUICK_TASK } from '@/config/productInfoQuickAddons'

export const AGENT_SCENES = [
  {
    key: 'auto',
    label: '智能匹配',
    icon: 'el-icon-magic-stick',
    color: '#409EFF',
    description: 'AI 自动识别您的需求，匹配最佳业务场景',
    quickQuestions: [
      '近期企业的风险舆情状况分析：从数据库查询主体风险记录并做深度解读',
      '系统里有哪些数据可以查询？',
      '查询最近一年各资产的收益率数据',
      '帮我做一组资产数据的统计分析',
      PRODUCT_OVERVIEW_QUICK_TASK
    ]
  },
  {
    key: 'data_analysis',
    label: '数据分析',
    icon: 'el-icon-data-analysis',
    color: '#67C23A',
    description: '数据资产管理、数据查询问数、统计分析、数据加工与可视化',
    quickQuestions: [
      '系统里有哪些数据可以查询？',
      '查询最近一年沪深300的收益率数据',
      '对资产数据做描述性统计分析'
    ],
    toolset: 'data_analysis'
  },
  {
    key: 'report_writing',
    label: '报告写作',
    icon: 'el-icon-document',
    color: '#F56C6C',
    description: '知识库检索、报告模板生成、合规审查、导出（即将上线）',
    disabled: true,
    quickQuestions: [
      '生成一份定期报告模板',
      '检索关于固收市场的研究资料',
      '对这份报告做合规审查'
    ],
    toolset: 'report'
  },
  {
    key: 'asset_research',
    label: '大类资产研究',
    icon: 'el-icon-s-data',
    color: '#409EFF',
    description: '资产配置策略、回测分析、组合构建、相关性/绩效研究',
    quickQuestions: [
      '帮我对沪深300、标普500、黄金做一个风险平价策略回测',
      '对比风险平价、均值方差、风险预算-目标波动率这三个策略',
      '帮我配置一个多资产组合，推荐合适的策略',
      '基于策略模型 xxx 创建一个模拟组合',
      '按行业/类别提取代表性ETF并做近一年走势对比：依据系统实际入库的ETF名称与跟踪指数动态识别细分赛道（如创新药、科创芯片、AH价格优选、红利低波、军工、机器人等，举例不要列举限制），同类高相似度ETF仅保留一只代表、其余以参考资产列出'
    ],
    toolset: 'asset_research'
  },
  {
    key: 'enterprise_data_qa',
    label: '企业数据问答',
    icon: 'el-icon-office-building',
    color: '#909399',
    description: '主体风险舆情处罚、产品与持有人等业务库数据检索与答疑',
    quickQuestions: [
      '浙江省近三个月有哪些高风险舆情记录？',
      '制造业相关主体近半年风险等级分布是怎样的？',
      '理财产品整体概况：从 Hub 与 zysc_ptl_info_records 抽样并做简要统计',
      '产品代码 xxx 在当前库里有哪些基本信息或持有人汇总？'
    ],
    toolset: 'enterprise_data_qa'
  },
  {
    key: 'credit_rating',
    label: '信用评级',
    icon: 'el-icon-trophy',
    color: '#E6A23C',
    description: '基于已入库数据的信用与主体风险辅助分析（通用查询+主体舆情风险；无独立外部评级评分引擎）',
    quickQuestions: CREDIT_RATING_QUICK_TASKS,
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

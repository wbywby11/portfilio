/**
 * 目标波动率预算旧模板（仅匹配已退役的旧 code，新统一模板 vol_scaled_budget 不再隐藏参数）。
 * 旧模板参数固定为产品默认，前端不展示、保存时强制写入。
 */
export function isRiskBudgetTargetVolTemplateCode(templateCode) {
  const c = (templateCode || '').toString();
  return c === 'risk_budget_target_vol' || c === 'risk_budget_vol_target';
}

export const RISK_BUDGET_TARGET_VOL_FIXED = {
  min_history_days: 260,
  vol_reset_threshold: 0.06,
  lookback_days: 260,
  tie_break_window: 22,
  enable_vol_reset: true
};

/** 模板 schema 中与顶层/固定逻辑重复的参数字段，在 risk_budget_target_vol 表单「模型参数」中不展示 */
export const RISK_BUDGET_TARGET_VOL_HIDDEN_PARAMETER_NAMES = [
  'lookback_days',
  'min_history_days',
  'vol_reset_threshold',
  'enable_vol_reset'
];

export function isRiskBudgetTargetVolHiddenTemplateParameter(name) {
  return RISK_BUDGET_TARGET_VOL_HIDDEN_PARAMETER_NAMES.includes(name);
}

/** 夏普率风险预算策略模板（仅匹配旧 code，新 code vol_scaled_budget 已统一参数） */
export function isSharpeRiskBudgetTemplateCode(templateCode) {
  const c = (templateCode || '').toString();
  return c === 'sharpe_risk_budget';
}

export const SHARPE_RISK_BUDGET_FIXED = {
  min_history_days: 260,
  vol_reset_threshold: 0.06,
  tie_break_window: 22,
  enable_vol_reset: true,
  selector_type: 'sharpe',
  asset_selection_count: 13,
  sharp_windows: '22,65,260',
  target_vol: 0.05,
  vol_trigger_threshold: 0.06
};

/** 夏普率风险预算策略：「模型参数」schema 中不在前端展示的参数（已固化或由资产选择卡片管理） */
export const SHARPE_RISK_BUDGET_HIDDEN_SCHEMA_PARAMETER_NAMES = [
  'target_vol',
  'max_leverage',
  'select_count',
  'vol_windows',
  'sharp_windows',
  'min_history_days',
  'enable_vol_reset',
  'vol_reset_threshold'
];

export function isSharpeRiskBudgetHiddenSchemaParameter(name) {
  return SHARPE_RISK_BUDGET_HIDDEN_SCHEMA_PARAMETER_NAMES.includes(name);
}

/** 主观配置 manual_allocation / manual_allocation_strategy */
export function isManualAllocationTemplateCode(templateCode) {
  const c = (templateCode || '').toString().toLowerCase();
  return c === 'manual_allocation' || c === 'manual_allocation_strategy';
}

/**
 * 主观策略：与日常实盘监控无关的模型参数字段，策略编辑「模型参数」中不展示；
 * 保存时与后端一并写入固定值。
 */
export const SUBJECTIVE_MONITOR_HIDDEN_SCHEMA_PARAMETER_NAMES = [
  'max_leverage',
  'auto_normalize',
  'fill_missing'
];

export function isSubjectiveMonitorHiddenSchemaParameter(name) {
  return SUBJECTIVE_MONITOR_HIDDEN_SCHEMA_PARAMETER_NAMES.includes(name);
}

/** 主观策略 parameters 内固定值（日常监控不使用，与产品默认一致） */
export const SUBJECTIVE_MONITOR_FIXED_PARAMETERS = {
  max_leverage: 1,
  auto_normalize: false,
  fill_missing: 'zero',
  target_vol: 0.05,
  vol_reset_threshold: 0.06,
  enable_vol_reset: false
};

/**
 * 实盘发布记录 monitor_scoped_changes：主观策略不展示的对比键
 *（与量化/混合动量相关的波动、窗口、历史长度等）
 */
export const SUBJECTIVE_MONITOR_HIDDEN_SCOPED_DIFF_KEYS = [
  'target_vol',
  'vol_trigger_threshold',
  'vol_reset_threshold',
  'volatility_threshold',
  'max_total_leverage',
  'mom_windows',
  'posi_windows',
  'smom_windows',
  'macd_windows',
  'macd_long_window',
  'reversal_windows',
  'momentum_windows',
  'min_history_days',
  'min_history_momentum',
  'min_history_reversal',
  'live_volatility_threshold',
  'enable_vol_reset',
  'fill_missing',
  'auto_normalize',
  'max_leverage',
  'weight_caps',
  'max_weight_dict',
  'tie_break_window'
];

export function isSubjectiveMonitorHiddenScopedDiffKey(key) {
  return SUBJECTIVE_MONITOR_HIDDEN_SCOPED_DIFF_KEYS.includes(key);
}

/** 策略详情「策略参数」块中不展示的 parameters 键 */
export const SUBJECTIVE_MONITOR_HIDDEN_DETAIL_PARAMETER_KEYS = [
  ...SUBJECTIVE_MONITOR_HIDDEN_SCHEMA_PARAMETER_NAMES,
  'target_vol',
  'vol_reset_threshold',
  'enable_vol_reset'
];

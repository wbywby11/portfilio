/**
 * 后台任务进度展示口径：monitor_tasks 文档 → 界面文案。
 *
 * 日常监控跑批与回测共用同一张任务表、同一个轮询端点
 * （GET /monitor/tasks/{task_id}），字段口径完全一致，因此百分比、阶段、
 * 告警色、已用时等派生逻辑收敛到这里，由进度面板与各页面横幅共同复用，
 * 避免两处展示对同一份任务数据给出不同结论。
 */

/** 任务类型（与后端 TASK_KIND_* / DONE_MESSAGE_BY_KIND 同值） */
export const TASK_KIND_LABEL = {
  monitor_init: '初始化',
  monitor_run: '日常运行',
  monitor_range: '区间补算',
  backtest_single: '回测',
  backtest_portfolio: '组合回测'
};

/** 任务阶段（与后端 update_progress 写入的 phase 同值） */
export const TASK_PHASE_LABEL = {
  pending: '等待执行',
  preparing: '准备中',
  loading: '加载数据',
  running: '逐日推演',
  engine: '引擎回测',
  finalizing: '保存结果',
  completed: '已完成',
  paused: '已暂停',
  failed: '失败',
  interrupted: '已中断'
};

/** 进行中的任务状态（与后端 ACTIVE_STATUSES 同值） */
const ACTIVE_STATUSES = ['pending', 'running'];

/** 任务是否仍在进行：决定进度条是否渲染、轮询是否继续 */
export function isTaskActive(task) {
  return !!task && ACTIVE_STATUSES.indexOf(task.status) >= 0;
}

/** 任务类型文案：补录重算是区间补算的一个变体，单独显示 */
export function taskKindLabel(task) {
  const t = task || {};
  if (t.params && t.params.replay) return '补录重算';
  return TASK_KIND_LABEL[t.kind || ''] || '运行';
}

/** 进度百分比：优先用后端算好的 percent，缺失时按 current/total 兜底 */
export function taskPercent(task) {
  const t = task;
  if (!t) return 0;
  if (t.status === 'completed') return 100;
  if (t.percent != null) {
    return Math.min(100, Math.max(0, Math.round(Number(t.percent))));
  }
  if (t.total) {
    return Math.min(100, Math.round((Number(t.current || 0) / Number(t.total)) * 100));
  }
  return 0;
}

/** 页面横幅进度文案：引擎类路径无总量时不给百分比，避免长期停在 0% */
export function taskBannerProgressText(task) {
  if (!task) return '—';
  return task.total ? `${taskPercent(task)}%` : '引擎计算中';
}

/**
 * el-progress 的 status：失败/中断标红，完成标绿。
 *
 * 本项目 element-ui 的 status 校验器只接受 success / exception / warning，
 * 传空串会触发 Vue 的 prop 校验告警；进行中的任务返回 null，让属性缺省。
 */
export function taskProgressStatus(task) {
  const st = task && task.status;
  if (st === 'failed' || st === 'interrupted') return 'exception';
  if (st === 'completed') return 'success';
  return null;
}

/** el-alert 的 type */
export function taskAlertType(task) {
  const st = task && task.status;
  if (st === 'failed' || st === 'interrupted') return 'error';
  if (st === 'completed') return 'success';
  if (st === 'paused') return 'warning';
  return 'info';
}

export function taskPhaseLabel(task) {
  return TASK_PHASE_LABEL[(task && task.phase) || ''] || '运行中';
}

/**
 * 是否展示「已处理 X / Y 个交易日」。
 *
 * 引擎类路径（phase=engine，含全部回测与组合监控）的 total 是「阶段 × 刻度」
 * 放大后的数，X/Y 没有字面意义；无逐日钩子时 total 为 0，同样不展示，
 * 避免出现「0 / —」。明细统一看 message（含阶段名、百分比与真实交易日数）。
 */
export function showTaskSteps(task) {
  const t = task || {};
  if (!t.total) return false;
  return t.phase !== 'engine';
}

/** 已用时文案：后端每次读取都按当前时间重算 elapsed_sec */
export function taskElapsedText(task) {
  const sec = task && task.elapsed_sec;
  if (sec == null) return '—';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`;
}

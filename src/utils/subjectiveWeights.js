/**
 * 主观权重归一化：合计缩放到 1，使用最大余数法分配。
 * 精度变更说明：原实现精确到百分之一（百分比整数），现升级为精确到万分之一（百分比的两位小数）。
 * 例如三等分结果为 [0.3333, 0.3333, 0.3334]（对应 33.33%、33.33%、33.34%）。
 * 函数名中的 "TwoDecimal" 现指百分比的两位小数。
 * @param {Record<string, number>} weights
 * @param {string[]} codes
 * @returns {Record<string, number>}
 */
export function normalizeWeightsToTwoDecimalSumOne(weights, codes) {
  const out = {};
  if (!codes || !codes.length) return out;
  let t = 0;
  codes.forEach(c => {
    t += Number(weights[c]) || 0;
  });
  if (t <= 0) {
    codes.forEach(c => {
      out[c] = 0;
    });
    return out;
  }
  // 精确到万分之一（百分比的两位小数），总计 10000 份
  const exact = codes.map(c => ((Number(weights[c]) || 0) / t) * 10000);
  const floor = exact.map(x => Math.floor(x + 1e-9));
  let rem = 10000 - floor.reduce((a, b) => a + b, 0);
  const byFrac = exact.map((x, i) => ({ i, f: x - floor[i] })).sort((a, b) => b.f - a.f);
  const bp = floor.slice();
  for (let k = 0; k < rem && k < byFrac.length; k++) {
    bp[byFrac[k].i] += 1;
  }
  // 转换回 0~1 范围，精确到 4 位小数
  codes.forEach((c, i) => {
    out[c] = bp[i] / 10000;
  });
  return out;
}

export function formatWeightSliderTooltip(val) {
  const n = Number(val);
  if (Number.isNaN(n)) return '';
  return `${(n * 100).toFixed(1)}%`;
}

export function subjectiveBarWidthPct(ratio) {
  if (ratio == null || Number.isNaN(Number(ratio))) return '0%';
  const w = Math.min(100, Math.max(0, Number(ratio) * 100));
  return `${w}%`;
}

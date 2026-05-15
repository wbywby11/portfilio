/**
 * 主观权重：与日常监控编辑弹窗一致的归一化（合计缩放到 1，百分之一精度，最大余数法）。
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
  const exact = codes.map(c => ((Number(weights[c]) || 0) / t) * 100);
  const floor = exact.map(x => Math.floor(x + 1e-9));
  let rem = 100 - floor.reduce((a, b) => a + b, 0);
  const byFrac = exact.map((x, i) => ({ i, f: x - floor[i] })).sort((a, b) => b.f - a.f);
  const bp = floor.slice();
  for (let k = 0; k < rem && k < byFrac.length; k++) {
    bp[byFrac[k].i] += 1;
  }
  codes.forEach((c, i) => {
    out[c] = bp[i] / 100;
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

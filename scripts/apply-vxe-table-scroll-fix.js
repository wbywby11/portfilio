/**
 * vxe-table：滚动时 refValidTooltip / refTooltip 可能尚未初始化 reactData，
 * 访问 reactData.visible 会抛错。对 es / lib 两份产物做幂等替换。
 * 见 issue 类场景：Cannot read properties of undefined (reading 'visible')
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');

const replacements = [
  {
    file: path.join(root, 'node_modules', 'vxe-table', 'es', 'table', 'src', 'methods.js'),
    pairs: [
      [
        'if (validTip && validTip.reactData.visible)',
        'if (validTip && validTip.reactData && validTip.reactData.visible)',
      ],
      [
        'if (tooltip && tooltip.reactData.visible)',
        'if (tooltip && tooltip.reactData && tooltip.reactData.visible)',
      ],
    ],
  },
  {
    file: path.join(root, 'node_modules', 'vxe-table', 'lib', 'table', 'src', 'methods.js'),
    pairs: [
      [
        'if(validTip&&validTip.reactData.visible){validTip.close();}if(tooltip&&tooltip.reactData.visible){tooltip.close();}',
        'if(validTip&&validTip.reactData&&validTip.reactData.visible){validTip.close();}if(tooltip&&tooltip.reactData&&tooltip.reactData.visible){tooltip.close();}',
      ],
    ],
  },
];

for (const { file, pairs } of replacements) {
  if (!fs.existsSync(file)) {
    continue;
  }
  let s = fs.readFileSync(file, 'utf8');
  const before = s;
  for (const [a, b] of pairs) {
    if (s.includes(a) && !s.includes(b)) {
      s = s.split(a).join(b);
    }
  }
  if (s !== before) {
    fs.writeFileSync(file, s, 'utf8');
    console.log('[apply-vxe-table-scroll-fix] patched', path.relative(root, file));
  }
}

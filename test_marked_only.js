const { marked } = require('marked');

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true
});

// 测试表格 Markdown
const testTable = `| 列1 | 列2 | 列3 |
|----|-----|-----|
| A | B | C |
| D | E | F |`;

const html = marked.parse(testTable);
console.log('=== marked 原始输出 ===');
console.log(html);

const { marked } = require('marked');
const DOMPurify = require('dompurify');

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true
});

// 测试表格 Markdown
const testTable = `
| 列1 | 列2 | 列3 |
|----|-----|-----|
| A | B | C |
| D | E | F |
`;

const html = marked.parse(testTable);
console.log('=== marked 原始输出 ===');
console.log(html);

const sanitized = DOMPurify.sanitize(html, {
  ALLOWED_TAGS: [
    'h1','h2','h3','h4','h5','h6','p','br','hr',
    'ul','ol','li','blockquote','pre','code',
    'table','thead','tbody','tr','th','td',
    'strong','em','del','a','img','span','div','sub','sup'
  ],
  ALLOWED_ATTR: ['href','src','alt','title','class','target','rel'],
  ALLOW_DATA_ATTR: false
});

console.log('\n=== DOMPurify 消毒后输出 ===');
console.log(sanitized);

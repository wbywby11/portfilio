/**
 * 从 zyDataDomain.mock.js 提取 REALISTIC_SEEDS 数据并保存为 JSON 格式
 * 
 * 使用方法:
 *   cd d:\portfilio
 *   node scripts/extract_zy_mock_seeds.js
 */
const fs = require('fs');
const path = require('path');

const mockJsPath = path.join(__dirname, '..', 'src', 'api', 'zyDataDomain.mock.js');
const outputPath = path.join(__dirname, 'zy_data_domain_seeds.json');

console.log('开始提取 ZY 数据域 Mock 种子数据...');
console.log(`源文件: ${mockJsPath}`);

try {
  // 读取 JS 文件
  const content = fs.readFileSync(mockJsPath, 'utf-8');
  
  // 提取 REALISTIC_SEEDS 对象
  // 匹配从 "const REALISTIC_SEEDS = {" 到最后一个 "}"
  const startMatch = content.match(/const REALISTIC_SEEDS = \{/);
  if (!startMatch) {
    throw new Error('未找到 REALISTIC_SEEDS 定义');
  }
  
  const startIndex = startMatch.index;
  
  // 从起始位置开始,计算大括号匹配
  let braceCount = 0;
  let endIndex = startIndex;
  let inString = false;
  let stringChar = '';
  let escapeNext = false;
  
  for (let i = startIndex; i < content.length; i++) {
    const char = content[i];
    
    if (escapeNext) {
      escapeNext = false;
      continue;
    }
    
    if (char === '\\') {
      escapeNext = true;
      continue;
    }
    
    if (!inString && (char === '"' || char === "'" || char === '`')) {
      inString = true;
      stringChar = char;
      continue;
    }
    
    if (inString && char === stringChar) {
      inString = false;
      continue;
    }
    
    if (!inString) {
      if (char === '{') {
        braceCount++;
      } else if (char === '}') {
        braceCount--;
        if (braceCount === 0) {
          endIndex = i;
          break;
        }
      }
    }
  }
  
  // 提取对象字符串
  let seedsStr = content.substring(startIndex, endIndex + 1);
  
  // 移除 "const REALISTIC_SEEDS = " 前缀
  seedsStr = seedsStr.replace(/^const REALISTIC_SEEDS = /, '');
  
  // 将 JS 对象语法转换为 JSON
  // 1. 移除单行注释
  seedsStr = seedsStr.replace(/\/\/.*$/gm, '');
  
  // 2. 移除多行注释
  seedsStr = seedsStr.replace(/\/\*[\s\S]*?\*\//g, '');
  
  // 3. 将单引号替换为双引号(仅在键名处)
  seedsStr = seedsStr.replace(/(\s*)([a-zA-Z0-9_]+)(\s*):(\s*)'/g, '$1"$2"$3: "');
  
  // 4. 替换末尾单引号
  seedsStr = seedsStr.replace(/:(\s*)'([^']*)'/g, ': "$2"');
  
  // 5. 移除尾逗号
  seedsStr = seedsStr.replace(/,(\s*[}\]])/g, '$1');
  
  // 6. 确保数字不被引号包裹
  // 注意:这里需要小心处理,不能破坏字符串中的数字
  
  // 解析为对象
  const seedsData = JSON.parse(seedsStr);
  
  // 保存到 JSON 文件
  fs.writeFileSync(outputPath, JSON.stringify(seedsData, null, 2), 'utf-8');
  
  console.log(`\n✓ 提取成功!`);
  console.log(`输出文件: ${outputPath}`);
  console.log(`集合数量: ${Object.keys(seedsData).length}`);
  console.log(`\n集合详情:`);
  
  let totalRecords = 0;
  for (const [collection, records] of Object.entries(seedsData)) {
    const count = Array.isArray(records) ? records.length : 0;
    totalRecords += count;
    console.log(`  ${collection}: ${count} 条`);
  }
  
  console.log(`\n总计: ${totalRecords} 条记录`);
  console.log(`\n下一步: 运行 Python 脚本导入到 MongoDB`);
  console.log(`  python scripts/import_zy_data_domain_mock.py`);
  
} catch (error) {
  console.error(`\n✗ 提取失败: ${error.message}`);
  console.error(`\n备选方案: 手动从 ${mockJsPath} 中复制 REALISTIC_SEEDS 对象`);
  console.error(`并粘贴到 ${outputPath} 中(需要确保是合法 JSON 格式)`);
  process.exit(1);
}

/**
 * 提取 ZY 数据域 Mock 数据为 JSON (健壮版)
 * 
 * 使用方法:
 *   node scripts/extract_zy_mock_seeds_v2.js
 */
const fs = require('fs');
const path = require('path');

const mockJsPath = path.join(__dirname, '..', 'src', 'api', 'zyDataDomain.mock.js');
const outputPath = path.join(__dirname, 'zy_data_domain_seeds_v2.json');

console.log('开始提取 ZY 数据域 Mock 种子数据 (健壮版)...');
console.log(`源文件: ${mockJsPath}`);

try {
  // 读取 JS 文件
  const content = fs.readFileSync(mockJsPath, 'utf-8');
  
  // 定位 REALISTIC_SEEDS 对象
  const startMatch = content.match(/const REALISTIC_SEEDS = \{/);
  if (!startMatch) {
    throw new Error('未找到 REALISTIC_SEEDS 定义');
  }
  
  const startIdx = startMatch.index;
  
  // 从起始位置开始,计算大括号匹配
  let braceCount = 0;
  let endIdx = startIdx;
  let inString = false;
  let stringChar = '';
  let escapeNext = false;
  
  for (let i = startIdx; i < content.length; i++) {
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
          endIdx = i;
          break;
        }
      }
    }
  }
  
  // 提取对象字符串
  let seedsStr = content.substring(startIdx, endIdx + 1);
  
  // 移除 "const REALISTIC_SEEDS = " 前缀
  seedsStr = seedsStr.replace(/^const REALISTIC_SEEDS = /, '');
  
  // 清理 JS 语法
  // 1. 移除注释
  seedsStr = seedsStr.replace(/\/\/[^\n]*/g, '');
  seedsStr = seedsStr.replace(/\/\*[\s\S]*?\*\//g, '');
  
  // 2. 移除换行和多余空白
  seedsStr = seedsStr.replace(/\s+/g, ' ');
  
  // 3. 处理键名 (添加引号)
  // 键名模式: 空白+字母数字下划线+冒号+空白
  seedsStr = seedsStr.replace(/\s([a-zA-Z_][a-zA-Z0-9_]*)\s*:/g, ' "$1":');
  
  // 4. 处理字符串值
  // 单引号字符串 -> 双引号字符串
  seedsStr = seedsStr.replace(/:\s*'([^']*)'/g, ': "$1"');
  
  // 5. 处理特殊字符转义
  seedsStr = seedsStr.replace(/\\'/g, "'");  // 解除转义的单引号
  seedsStr = seedsStr.replace(/\\n/g, ' ');  // 换行符 -> 空格
  seedsStr = seedsStr.replace(/\\"/g, '"');  // 解除转义的双引号
  
  // 6. 处理数字 (移除前导零,保留科学计数法)
  seedsStr = seedsStr.replace(/:(\s*)0+(\d)/g, ': $1$2');  // 0123 -> 123
  seedsStr = seedsStr.replace(/:(\s*)0+(\.)/g, ': $10.');  // 0.5 保持
  
  // 7. 移除尾逗号
  seedsStr = seedsStr.replace(/,(\s*[}\]])/g, '$1');
  
  // 8. 处理 true/false/null
  seedsStr = seedsStr.replace(/:(\s*)true(\s*[,\}])/g, ': true$2');
  seedsStr = seedsStr.replace(/:(\s*)false(\s*[,\}])/g, ': false$2');
  seedsStr = seedsStr.replace(/:(\s*)null(\s*[,\}])/g, ': null$2');
  
  // 解析 JSON
  let seedsData;
  try {
    seedsData = JSON.parse(seedsStr);
  } catch (e) {
    // 详细错误报告
    console.error(`JSON 解析失败: ${e.message}`);
    
    // 尝试定位错误位置
    const pos = parseInt(e.message.match(/position (\d+)/)?.[1] || 0);
    const contextStart = Math.max(0, pos - 50);
    const contextEnd = Math.min(seedsStr.length, pos + 50);
    const context = seedsStr.substring(contextStart, contextEnd);
    
    console.error(`错误位置附近: ...${context}...`);
    console.error(`字符 (${pos}): '${seedsStr[pos]}' (代码 ${seedsStr.charCodeAt(pos)})`);
    
    // 尝试更宽松的解析
    console.log('尝试宽松解析...');
    seedsData = parseLoosely(seedsStr);
  }
  
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
  
} catch (error) {
  console.error(`\n✗ 提取失败: ${error.message}`);
  process.exit(1);
}

// 宽松解析函数
function parseLoosely(str) {
  const result = {};
  
  // 匹配 collection: [...]
  const collectionRegex = /"([dwt][a-z_]+)":\s*\[([\s\S]*?)\](?=[,}\s])/g;
  let match;
  
  while ((match = collectionRegex.exec(str)) !== null) {
    const collectionName = match[1];
    const arrayContent = match[2];
    
    const records = [];
    
    // 匹配每个对象 {...}
    const objRegex = /\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g;
    let objMatch;
    
    while ((objMatch = objRegex.exec(arrayContent)) !== null) {
      const objStr = objMatch[1];
      const obj = parseObjectLoosely(objStr);
      if (obj && Object.keys(obj).length > 0) {
        records.push(obj);
      }
    }
    
    result[collectionName] = records;
  }
  
  return result;
}

function parseObjectLoosely(objStr) {
  const result = {};
  
  // 匹配键值对
  const patterns = [
    // 数字值
    [/([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)/g, 'number'],
    // 布尔值
    [/:(\s*)(true|false)/g, 'bool'],
    // null
    [/:(\s*)null/g, 'null'],
    // 字符串 (双引号)
    [/"([^"]*)"/g, 'string_dq'],
    // 字符串 (单引号)
    [/'([^']*)'/g, 'string_sq'],
  ];
  
  // 使用更简单的方法 - 逐行解析
  const pairs = objStr.split(',');
  
  for (const pair of pairs) {
    const colonIdx = pair.indexOf(':');
    if (colonIdx === -1) continue;
    
    let key = pair.substring(0, colonIdx).trim();
    let value = pair.substring(colonIdx + 1).trim();
    
    // 清理键名
    key = key.replace(/"/g, '').replace(/'/g, '');
    
    if (!key) continue;
    
    // 清理值
    value = value.replace(/"/g, '').replace(/'/g, '');
    
    // 判断类型
    if (value === 'null') {
      result[key] = null;
    } else if (value === 'true') {
      result[key] = true;
    } else if (value === 'false') {
      result[key] = false;
    } else if (/^-?\d+\.?\d*(?:[eE][+-]?\d+)?$/.test(value)) {
      result[key] = parseFloat(value);
    } else {
      result[key] = value;
    }
  }
  
  return result;
}
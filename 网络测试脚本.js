/**
 * 网络连接测试脚本
 * 在浏览器控制台（F12 -> Console）中直接运行此脚本
 * 或者复制整个脚本内容到控制台执行
 */

(function() {
  const baseURL = 'http://127.0.0.1:8000';
  
  console.log('='.repeat(60));
  console.log('🔍 开始测试后端网络连接');
  console.log('Base URL:', baseURL);
  console.log('='.repeat(60));
  
  // 测试1: 基础连接测试
  async function testBasicConnection() {
    console.log('\n📡 测试1: 基础连接测试');
    try {
      const response = await fetch(`${baseURL}/docs`, { 
        method: 'HEAD',
        mode: 'no-cors' // 避免 CORS 问题
      });
      console.log('✅ 基础连接成功');
      return true;
    } catch (error) {
      console.error('❌ 基础连接失败:', error.message);
      console.error('   可能原因: 后端服务未运行或端口不正确');
      return false;
    }
  }
  
  // 测试2: API 端点测试
  async function testAPIEndpoint() {
    console.log('\n📡 测试2: API 端点测试');
    try {
      const response = await fetch(`${baseURL}/api/v1/strategy-models/`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      console.log('状态码:', response.status);
      console.log('状态文本:', response.statusText);
      
      if (response.ok) {
        const data = await response.json();
        console.log('✅ API 调用成功');
        console.log('响应数据:', data);
        return true;
      } else {
        console.warn('⚠️ API 返回非成功状态:', response.status);
        const text = await response.text();
        console.log('响应内容:', text);
        return false;
      }
    } catch (error) {
      console.error('❌ API 调用失败:', error.message);
      
      if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
        console.error('   这是网络错误，可能原因:');
        console.error('   1. 后端服务未运行');
        console.error('   2. 后端服务运行在不同的端口');
        console.error('   3. CORS 跨域问题');
        console.error('   4. 防火墙阻止连接');
      }
      
      return false;
    }
  }
  
  // 测试3: CORS 测试
  async function testCORS() {
    console.log('\n📡 测试3: CORS 跨域测试');
    try {
      const response = await fetch(`${baseURL}/api/v1/strategy-models/`, {
        method: 'OPTIONS',
        headers: {
          'Origin': window.location.origin,
          'Access-Control-Request-Method': 'GET',
          'Access-Control-Request-Headers': 'Content-Type'
        }
      });
      
      const corsHeaders = {
        'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin'),
        'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods'),
        'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers')
      };
      
      console.log('CORS 响应头:', corsHeaders);
      
      if (corsHeaders['Access-Control-Allow-Origin']) {
        console.log('✅ CORS 配置正常');
        return true;
      } else {
        console.warn('⚠️ 未检测到 CORS 响应头');
        return false;
      }
    } catch (error) {
      console.error('❌ CORS 测试失败:', error.message);
      return false;
    }
  }
  
  // 测试4: 端口检查
  function checkPort() {
    console.log('\n📡 测试4: 端口检查');
    console.log('前端请求的 URL:', baseURL);
    console.log('当前页面地址:', window.location.origin);
    console.log('建议: 确保后端服务运行在 8000 端口');
    console.log('检查命令: netstat -ano | findstr :8000');
  }
  
  // 执行所有测试
  async function runAllTests() {
    checkPort();
    
    const results = {
      basic: await testBasicConnection(),
      api: await testAPIEndpoint(),
      cors: await testCORS()
    };
    
    console.log('\n' + '='.repeat(60));
    console.log('📊 测试结果汇总');
    console.log('='.repeat(60));
    console.log('基础连接:', results.basic ? '✅ 通过' : '❌ 失败');
    console.log('API 调用:', results.api ? '✅ 通过' : '❌ 失败');
    console.log('CORS 配置:', results.cors ? '✅ 通过' : '⚠️ 未检测到');
    console.log('='.repeat(60));
    
    if (!results.basic) {
      console.log('\n💡 建议:');
      console.log('1. 检查后端服务是否运行: cd D:\\portfilio-end && python main.py');
      console.log('2. 检查端口是否正确: 访问 http://127.0.0.1:8000/docs');
      console.log('3. 检查防火墙设置');
    }
    
    if (!results.api && results.basic) {
      console.log('\n💡 建议:');
      console.log('1. 检查 API 路径是否正确');
      console.log('2. 检查后端路由是否注册');
      console.log('3. 查看后端日志中的错误信息');
    }
    
    if (!results.cors) {
      console.log('\n💡 建议:');
      console.log('1. 检查后端 CORS 配置');
      console.log('2. 确保后端允许当前前端域名的跨域请求');
    }
  }
  
  // 自动运行测试
  runAllTests();
})();

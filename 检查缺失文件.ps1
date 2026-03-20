# 检查缺失文件脚本
# 使用方法：在项目根目录运行 .\检查缺失文件.ps1

Write-Host "=== 检查必需文件 ===" -ForegroundColor Green

$missingFiles = @()
$existingFiles = @()

# 定义必需文件列表
$requiredFiles = @(
    "src\api\asset.js",
    "src\api\strategy.js",
    "src\api\portfolio.js",
    "src\api\analysis.js",
    "src\utils\request.js",
    "src\views\portfolio\PortfolioCreate.vue",
    "src\views\portfolio\PortfolioDetail.vue",
    "src\views\strategy\BacktestExecution.vue",
    "src\views\strategy\BacktestResult.vue",
    "src\views\strategy\backtest\SingleStrategyResult.vue",
    "src\views\strategy\backtest\MultiStrategyComparison.vue"
)

# 检查每个文件
foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "✓ $file" -ForegroundColor Green
        $existingFiles += $file
    } else {
        Write-Host "✗ $file (缺失)" -ForegroundColor Red
        $missingFiles += $file
    }
}

Write-Host "`n=== 检查结果 ===" -ForegroundColor Yellow
Write-Host "存在文件: $($existingFiles.Count)" -ForegroundColor Green
Write-Host "缺失文件: $($missingFiles.Count)" -ForegroundColor Red

if ($missingFiles.Count -gt 0) {
    Write-Host "`n缺失的文件列表:" -ForegroundColor Red
    foreach ($file in $missingFiles) {
        Write-Host "  - $file" -ForegroundColor Red
    }
    Write-Host "`n请从原项目复制这些文件！" -ForegroundColor Yellow
} else {
    Write-Host "`n所有必需文件都存在！" -ForegroundColor Green
    Write-Host "如果仍有编译错误，请尝试：" -ForegroundColor Yellow
    Write-Host "  1. 删除 node_modules 和 package-lock.json" -ForegroundColor Cyan
    Write-Host "  2. 运行 npm install" -ForegroundColor Cyan
    Write-Host "  3. 运行 npm run dev" -ForegroundColor Cyan
}

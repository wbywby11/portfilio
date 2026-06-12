# 0228 版本标记回退脚本
# 用途：撤销 0228 版本标记相关变更
# 执行：PowerShell -ExecutionPolicy Bypass -File rollback_0228.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== 0228 版本回退 ===" -ForegroundColor Cyan

# portfilio 回退
$portfilioPath = Join-Path (Split-Path -Parent $scriptDir) "portfilio"
if (Test-Path $portfilioPath) {
    Write-Host "`n[portfilio] 回退中..." -ForegroundColor Yellow
    $pkgPath = Join-Path $portfilioPath "package.json"
    if (Test-Path $pkgPath) {
        (Get-Content $pkgPath -Raw -Encoding UTF8) -replace '"version": "0\.2\.28"', '"version": "1.0.0"' | Set-Content $pkgPath -NoNewline -Encoding UTF8
        Write-Host "  - package.json 版本已恢复为 1.0.0" -ForegroundColor Green
    }
    $versionFile = Join-Path $portfilioPath "VERSION"
    if (Test-Path $versionFile) {
        Remove-Item $versionFile -Force
        Write-Host "  - 已删除 VERSION" -ForegroundColor Green
    }
    # CHANGELOG 保留，仅提示
    Write-Host "  - CHANGELOG_0228_后变更记录.md 已保留（可手动删除）" -ForegroundColor Gray
} else {
    Write-Host "`n[portfilio] 路径不存在: $portfilioPath" -ForegroundColor Red
}

# portfilio-end 回退
Write-Host "`n[portfilio-end] 回退中..." -ForegroundColor Yellow
$settingsPath = Join-Path $scriptDir "app\config\settings.py"
if (Test-Path $settingsPath) {
    (Get-Content $settingsPath -Raw -Encoding UTF8) -replace 'APP_VERSION: str = "0\.2\.28"[^\r\n]*', 'APP_VERSION: str = "1.0.0"' | Set-Content $settingsPath -NoNewline -Encoding UTF8
    Write-Host "  - app/config/settings.py 版本已恢复为 1.0.0" -ForegroundColor Green
}
$versionFile = Join-Path $scriptDir "VERSION"
if (Test-Path $versionFile) {
    Remove-Item $versionFile -Force
    Write-Host "  - 已删除 VERSION" -ForegroundColor Green
}
Write-Host "  - CHANGELOG_0228_后变更记录.md 已保留（可手动删除）" -ForegroundColor Gray
Write-Host "  - 合并代码变更记录_0228后.md 已保留（可手动删除）" -ForegroundColor Gray

Write-Host "`n=== 回退完成 ===" -ForegroundColor Cyan
Write-Host "请人工核对 package.json 与 settings.py 的修改结果。" -ForegroundColor Yellow

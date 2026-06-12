# 导入关联 Mock 数据到 MongoDB
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "ZY 数据域关联 Mock 数据导入" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 执行 Python 脚本
python.exe scripts/generate_and_import_associated_mock.py

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "导入完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green

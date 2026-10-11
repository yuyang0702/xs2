# Quick rebuild script
Set-Location "C:\xs2\DeterminFlow\web"
npm run build
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ 前端构建成功！" -ForegroundColor Green
    Write-Host "请重启服务以查看更新。" -ForegroundColor Cyan
} else {
    Write-Host "✗ 构建失败，请检查错误信息。" -ForegroundColor Red
}
Read-Host "按回车键退出"

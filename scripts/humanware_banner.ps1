# Humanware Engine Startup Banner
# 在 DeterminFlow 启动时显示的友好提示

function Show-HumanwareBanner {
    param(
        [string]$RootPath
    )

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Magenta
    Write-Host "✨ Humanware Engine" -ForegroundColor Magenta
    Write-Host "========================================" -ForegroundColor Magenta
    Write-Host ""

    # 检查 Humanware Engine 是否存在
    $pluginBasePath = Join-Path $RootPath "data\plugins\checkouts\xs2-novel-flywheel"
    $humanwareFound = $false

    if (Test-Path $pluginBasePath) {
        $checkoutDirs = Get-ChildItem -Path $pluginBasePath -Directory
        foreach ($dir in $checkoutDirs) {
            $enginePath = Join-Path $dir.FullName "resources\script-library\xs2\humanware_engine"
            if (Test-Path $enginePath) {
                $humanwareFound = $true
                Write-Host "✅ Humanware Engine 已安装" -ForegroundColor Green
                Write-Host "   让你的小说更有人味！" -ForegroundColor Cyan
                Write-Host ""

                # 检查是否已初始化
                $metaDir = Join-Path $RootPath "meta"
                $voiceFile = Join-Path $metaDir "character_voices.json"
                if (Test-Path $voiceFile) {
                    Write-Host "✅ 系统已初始化" -ForegroundColor Green
                } else {
                    Write-Host "ℹ️  首次使用？" -ForegroundColor Yellow
                    Write-Host "   初始化: python humanware_quickstart.py --action init" -ForegroundColor White
                    Write-Host "   演示:   python humanware_demo.py" -ForegroundColor White
                }
                break
            }
        }
    }

    if (-not $humanwareFound) {
        # 检查工具是否存在
        $quickstart = Join-Path $RootPath "humanware_quickstart.py"
        $demo = Join-Path $RootPath "humanware_demo.py"

        if ((Test-Path $quickstart) -and (Test-Path $demo)) {
            Write-Host "📦 Humanware Engine 工具已就绪" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "快速开始:" -ForegroundColor Cyan
            Write-Host "  1. 查看效果: python humanware_demo.py" -ForegroundColor White
            Write-Host "  2. 初始化:   python humanware_quickstart.py --action init" -ForegroundColor White
            Write-Host ""
            Write-Host "文档:" -ForegroundColor Cyan
            Write-Host "  快速入门: HUMANWARE_LETTER_TO_YOU.md" -ForegroundColor White
            Write-Host "  完整指南: HUMANWARE_IMPLEMENTATION_GUIDE.md" -ForegroundColor White
        }
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Magenta
    Write-Host ""
}

# 导出函数
Export-ModuleMember -Function Show-HumanwareBanner

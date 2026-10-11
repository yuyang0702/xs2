$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Url = "http://127.0.0.1:8020/docs"

function Write-Info([string]$Message) {
    Write-Host "[DeterminFlow] $Message" -ForegroundColor Cyan
}

function Write-Success([string]$Message) {
    Write-Host "[DeterminFlow] $Message" -ForegroundColor Green
}

function Write-Error-Custom([string]$Message) {
    Write-Host "[DeterminFlow] $Message" -ForegroundColor Red
}

function Test-Service([string]$Address) {
    try {
        $response = Invoke-WebRequest -Uri $Address -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Test-DependenciesInstalled {
    try {
        $packages = @("openai", "fastapi", "langgraph")
        foreach ($package in $packages) {
            $result = & $venvPython -c "import $package" 2>&1
            if ($LASTEXITCODE -ne 0) {
                return $false
            }
        }
        return $true
    } catch {
        return $false
    }
}

if (Test-Service $Url) {
    Write-Info "The service is already running; opening the browser."
    Start-Process $Url
    exit 0
}

function Get-PythonCommand {
    $candidates = @(
        @{ File = (Join-Path $Root ".venv\Scripts\python.exe"); Kind = "path" },
        @{ File = "py"; Kind = "launcher" },
        @{ File = "python"; Kind = "path" }
    )

    foreach ($candidate in $candidates) {
        try {
            if ($candidate.Kind -eq "path" -and $candidate.File -ne "python" -and -not (Test-Path $candidate.File)) {
                continue
            }
            if ($candidate.File -eq "py") {
                $versionText = (& py -3.11 -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))" 2>$null | Select-Object -Last 1)
            } else {
                $versionText = (& $candidate.File -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))" 2>$null | Select-Object -Last 1)
            }
            if ($versionText -match '^([0-9]+)\.([0-9]+)$') {
                $version = [version]("{0}.{1}" -f $Matches[1], $Matches[2])
                if ($version -ge [version]"3.11") {
                    return $candidate
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

$python = Get-PythonCommand
if ($null -eq $python) {
    Write-Host "Python 3.11 or newer was not found." -ForegroundColor Red
    Write-Host "Install Python 3.11+ and run this launcher again."
    Write-Host "For a ready-to-run build, open: https://github.com/alikon-art/DeterminFlow/releases/latest"
    Read-Host "Press Enter to exit"
    exit 1
}

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Info "Creating the Python virtual environment."
    if ($python.File -eq "py") {
        & py -3.11 -m venv (Join-Path $Root ".venv")
    } else {
        & $python.File -m venv (Join-Path $Root ".venv")
    }
}

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment creation failed: $venvPython"
}

# === 自动检测并安装依赖 ===
$requirements = Join-Path $Root "requirements.txt"
$requirementsDev = Join-Path $Root "requirements-dev.txt"
$dependencyMarker = Join-Path $Root ".venv\.determinflow-dependencies-ready"

Write-Info "Checking dependencies..."

# 检查 requirements.txt 和 requirements-dev.txt
$hasRequirements = (Test-Path $requirements) -or (Test-Path $requirementsDev)

if ($hasRequirements) {
    $needsInstall = $false

    # 检查依赖标记文件
    if (-not (Test-Path $dependencyMarker)) {
        $needsInstall = $true
        Write-Info "Dependencies marker not found, installing dependencies."
    } else {
        # 检查依赖文件是否更新过
        $markerTime = (Get-Item $dependencyMarker).LastWriteTimeUtc

        if ((Test-Path $requirements) -and (Get-Item $requirements).LastWriteTimeUtc -gt $markerTime) {
            $needsInstall = $true
            Write-Info "requirements.txt has been updated, reinstalling dependencies."
        }

        if ((Test-Path $requirementsDev) -and (Get-Item $requirementsDev).LastWriteTimeUtc -gt $markerTime) {
            $needsInstall = $true
            Write-Info "requirements-dev.txt has been updated, reinstalling dependencies."
        }

        # 检查关键包是否已安装
        if (-not (Test-DependenciesInstalled)) {
            $needsInstall = $true
            Write-Info "Some dependencies are missing, reinstalling."
        }
    }

    if ($needsInstall) {
        Write-Info "Installing Python dependencies; this may take a few minutes."

        # 升级 pip
        Write-Info "Upgrading pip..."
        & $venvPython -m pip install --upgrade pip | Out-Null

        # 安装主要依赖
        if (Test-Path $requirements) {
            Write-Info "Installing requirements.txt..."
            & $venvPython -m pip install -r $requirements
        }

        # 安装开发依赖
        if (Test-Path $requirementsDev) {
            Write-Info "Installing requirements-dev.txt..."
            & $venvPython -m pip install -r $requirementsDev
        }

        # 更新标记文件
        Set-Content -Path $dependencyMarker -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding UTF8
        Write-Success "Dependencies installed successfully."
    } else {
        Write-Success "All dependencies are up to date."
    }
} else {
    # 兼容旧的 requirements.lock 文件
    $requirementsLock = Join-Path $Root "requirements.lock"

    if (-not (Test-Path $requirementsLock)) {
        Write-Host "Error: requirements.txt/requirements-dev.txt or requirements.lock not found" -ForegroundColor Red
        exit 1
    }

    if (-not (Test-Path $dependencyMarker) -or (Get-Item $requirementsLock).LastWriteTimeUtc -gt (Get-Item $dependencyMarker).LastWriteTimeUtc) {
        Write-Info "Installing Python dependencies; the first run can take a few minutes."
        & $venvPython -m pip install -r $requirementsLock
        Set-Content -Path $dependencyMarker -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding UTF8
    }
}

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}

$modelConfig = Join-Path $Root "config\models_config.json"
if (-not (Test-Path $modelConfig)) {
    Copy-Item (Join-Path $Root "config\models_config.example.json") $modelConfig
}

# === 自动检测和安装必需的插件 ===
Write-Info "Checking and installing required plugins..."

$setupPluginsScript = Join-Path $Root "setup_plugins.py"
if (Test-Path $setupPluginsScript) {
    try {
        # 设置环境变量以支持 UTF-8
        $env:PYTHONIOENCODING = "utf-8"

        # 使用 -NoNewline 和适当的编码处理
        $pluginCheckProcess = Start-Process -FilePath $venvPython `
            -ArgumentList @($setupPluginsScript) `
            -WorkingDirectory $Root `
            -PassThru `
            -RedirectStandardOutput (Join-Path $env:TEMP "plugin_check_output.txt") `
            -RedirectStandardError (Join-Path $env:TEMP "plugin_check_error.txt") `
            -NoNewWindow

        $pluginCheckProcess.WaitForExit()

        # 读取输出文件
        $outputFile = Join-Path $env:TEMP "plugin_check_output.txt"
        $errorFile = Join-Path $env:TEMP "plugin_check_error.txt"

        if (Test-Path $outputFile) {
            $output = Get-Content $outputFile -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($output) {
                $output | ForEach-Object { Write-Host "  $_" }
            }
            Remove-Item $outputFile -Force -ErrorAction SilentlyContinue
        }

        if ($pluginCheckProcess.ExitCode -eq 0) {
            Write-Success "Plugin check completed successfully."
        } else {
            Write-Host "Warning: Plugin check returned code $($pluginCheckProcess.ExitCode)." -ForegroundColor Yellow
            if (Test-Path $errorFile) {
                $errorMsg = Get-Content $errorFile -Encoding UTF8 -ErrorAction SilentlyContinue
                if ($errorMsg) {
                    Write-Host "  Error details: $errorMsg" -ForegroundColor Yellow
                }
                Remove-Item $errorFile -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        Write-Host "Warning: Plugin check script failed: $_" -ForegroundColor Yellow
    }
} else {
    Write-Info "Plugin setup script not found, skipping plugin check."
}

Write-Info "Starting the local service."
$process = Start-Process -FilePath $venvPython -ArgumentList @("run.py") -WorkingDirectory $Root -PassThru

$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        Write-Host "The backend process exited with code $($process.ExitCode)." -ForegroundColor Red
        Write-Host "Check the backend window for details."
        Read-Host "Press Enter to exit"
        exit 1
    }
    if (Test-Service $Url) {
        $ready = $true
        break
    }
}

if (-not $ready) {
    Write-Host "The service did not become ready within 180 seconds." -ForegroundColor Yellow
    exit 1
}

Write-Info "Service ready; opening $Url"
Start-Process $Url

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

# 寻找可用的 Python 3.11+
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

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════"
Write-Host "  DeterminFlow 自动启动脚本"
Write-Host "════════════════════════════════════════════════════════════"
Write-Host ""

# 步骤 1: 检查服务是否已运行
if (Test-Service $Url) {
    Write-Info "The service is already running; opening the browser."
    Start-Process $Url
    exit 0
}

# 步骤 2: 寻找 Python
Write-Info "Looking for Python 3.11+..."
$python = Get-PythonCommand
if ($null -eq $python) {
    Write-Error-Custom "Python 3.11 or newer was not found."
    Write-Host "Please install Python 3.11+ and run this launcher again."
    Write-Host "Download from: https://www.python.org/downloads/"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Success "Found Python at: $($python.File)"

# 步骤 3: 创建虚拟环境（如需要）
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Info "Creating Python virtual environment..."
    if ($python.File -eq "py") {
        & py -3.11 -m venv (Join-Path $Root ".venv")
    } else {
        & $python.File -m venv (Join-Path $Root ".venv")
    }

    if (-not (Test-Path $venvPython)) {
        Write-Error-Custom "Failed to create virtual environment"
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Success "Virtual environment created"
}

# 步骤 4: 自动检测和安装依赖
Write-Info "Checking dependencies..."

$requirements = Join-Path $Root "requirements.txt"
$dependencyMarker = Join-Path $Root ".venv\.determinflow-dependencies-ready"
$needsInstall = $false

if ((Test-Path $requirements)) {
    if (-not (Test-Path $dependencyMarker)) {
        $needsInstall = $true
    } else {
        $markerTime = (Get-Item $dependencyMarker).LastWriteTimeUtc
        if ((Get-Item $requirements).LastWriteTimeUtc -gt $markerTime) {
            $needsInstall = $true
        }
    }
}

if ($needsInstall) {
    Write-Info "Installing Python dependencies (this may take a few minutes)..."

    # 升级 pip
    Write-Info "Upgrading pip..."
    & $venvPython -m pip install --upgrade pip 2>&1 | Out-Null

    # 安装依赖
    if (Test-Path $requirements) {
        Write-Info "Installing from requirements.txt..."
        & $venvPython -m pip install -r $requirements 2>&1 | Out-Null
        Write-Success "Dependencies installed"
    }

    # 创建标记
    Set-Content -Path $dependencyMarker -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding UTF8
} else {
    Write-Success "All dependencies are up to date"
}

# 步骤 5: 配置文件初始化
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Info "Creating .env file..."
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env") -ErrorAction SilentlyContinue
}

$modelConfig = Join-Path $Root "config\models_config.json"
if (-not (Test-Path $modelConfig)) {
    Write-Info "Creating models configuration..."
    Copy-Item (Join-Path $Root "config\models_config.example.json") $modelConfig -ErrorAction SilentlyContinue
}

# 步骤 6: 启动服务
Write-Info "Starting the local service..."
$process = Start-Process -FilePath $venvPython -ArgumentList @("run.py") -WorkingDirectory $Root -PassThru

$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        Write-Error-Custom "The backend process exited with code $($process.ExitCode)."
        Write-Host "Check the output above for details."
        Read-Host "Press Enter to exit"
        exit 1
    }
    if (Test-Service $Url) {
        $ready = $true
        break
    }
}

if (-not $ready) {
    Write-Error-Custom "The service did not become ready within 180 seconds."
    exit 1
}

Write-Success "Service ready!"
Write-Info "Opening $Url in browser..."
Start-Process $Url

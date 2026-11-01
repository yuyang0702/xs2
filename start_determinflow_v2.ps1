param([switch]$NoBrowser, [switch]$PrepareOnly)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

try {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    # Executable paths and arguments are separate; a space in Root is ordinary.
    $candidates = @(
        @{ Executable = $venvPython; Arguments = @() },
        @{ Executable = "py"; Arguments = @("-3.11") },
        @{ Executable = "py"; Arguments = @("-3") },
        @{ Executable = "python"; Arguments = @() },
        @{ Executable = "python3"; Arguments = @() }
    )
    $selected = $null
    foreach ($candidate in $candidates) {
        $executable = $candidate.Executable
        $candidateArgs = $candidate.Arguments
        if (-not (Get-Command $executable -ErrorAction SilentlyContinue)) { continue }
        try {
            & $executable @candidateArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
            if ($LASTEXITCODE -eq 0) { $selected = $candidate; break }
        } catch { continue }
    }
    if ($null -eq $selected) { throw "Python 3.11+ was not found. Install Python and retry." }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $executable = $selected.Executable
        $candidateArgs = $selected.Arguments
        & $executable @candidateArgs -m venv (Join-Path $Root ".venv")
        if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed (exit $LASTEXITCODE)." }
    } elseif ($selected.Executable -ne $venvPython) {
        throw "The existing .venv is unusable or older than Python 3.11. Repair it before startup."
    }
    $launchArgs = @((Join-Path $Root "scripts\start_local.py"))
    if ($NoBrowser) { $launchArgs += "--no-browser" }
    if ($PrepareOnly) { $launchArgs += "--prepare-only" }
    & $venvPython @launchArgs
    exit $LASTEXITCODE
} catch {
    Write-Host "DeterminFlow startup failed: $_" -ForegroundColor Red
    exit 1
}

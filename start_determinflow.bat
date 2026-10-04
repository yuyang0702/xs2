@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_determinflow.ps1"
if errorlevel 1 (
  echo.
  echo DeterminFlow startup failed. See the message above.
  pause
)
endlocal

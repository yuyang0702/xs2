@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_determinflow_v2.ps1" %*
set "startup_exit=%ERRORLEVEL%"
if not "%startup_exit%"=="0" (
  echo.
  echo DeterminFlow startup failed. See the error above and logs\startup_*.log.
  if not "%DETERMINFLOW_NO_PAUSE%"=="1" pause
)
endlocal & exit /b %startup_exit%

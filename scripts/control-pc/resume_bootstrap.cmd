@echo off
setlocal
cd /d "%~dp0\..\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\control-pc\bootstrap_wsl.ps1
if errorlevel 1 (
  echo.
  echo CONTROL PC BOOTSTRAP FAILED. Keep this window open for diagnostics.
  pause
)
endlocal

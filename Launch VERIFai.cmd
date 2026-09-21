@echo off
setlocal
cd /d "%~dp0"

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo PowerShell is required to launch VERIFai.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launch.ps1" %*
set "VERIFAI_EXIT=%ERRORLEVEL%"

if not "%VERIFAI_EXIT%"=="0" (
  echo.
  echo VERIFai launcher closed. Review the message above if startup failed.
  pause
)

exit /b %VERIFAI_EXIT%

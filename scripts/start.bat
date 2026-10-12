@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_app_host.ps1" -RepoPath "%SCRIPT_DIR%.."
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo The clinic antiviral tool did not start.
)
exit /b %EXIT_CODE%

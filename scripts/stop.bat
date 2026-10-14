@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop_app_host.ps1" -RepoPath "%SCRIPT_DIR%.."
exit /b %ERRORLEVEL%

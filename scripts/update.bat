@echo off
setlocal
cd /d "%~dp0.."
git pull --ff-only
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt

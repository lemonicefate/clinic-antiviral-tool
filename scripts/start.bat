@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.12 virtual environment not found. Create it with: py -3.12 -m venv .venv
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

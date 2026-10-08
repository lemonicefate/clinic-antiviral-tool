@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "$processes = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -like '*uvicorn app.main:app*' }; if (-not $processes) { Write-Host 'No clinic antiviral process found.' } else { $processes | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Stopped PID ' + $_.ProcessId) } }"

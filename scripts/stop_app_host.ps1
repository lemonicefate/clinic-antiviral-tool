[CmdletBinding()]
param(
    [string]$TaskName = 'ClinicAntiviralTool',
    [string]$RepoPath
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent $PSScriptRoot
}
$repo = (Get-Item -LiteralPath $RepoPath -ErrorAction Stop).FullName
$expectedPython = [IO.Path]::GetFullPath((Join-Path $repo '.venv\Scripts\python.exe'))

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task -and $task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Host ("Stopped scheduled task {0}." -f $TaskName)
}
elseif ($null -ne $task) {
    Write-Host ("Scheduled task {0} is not running." -f $TaskName)
}

if (-not (Test-Path -LiteralPath $expectedPython -PathType Leaf)) {
    Write-Host 'No repository venv Python process can be running because the executable is missing.'
    exit 0
}

$processes = @(
    Get-CimInstance -ClassName Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(\.exe)?$' -and
        [StringComparer]::OrdinalIgnoreCase.Equals([string]$_.ExecutablePath, $expectedPython) -and
        [string]$_.CommandLine -match '(?i)(?:-m\s+app\.startup\b|uvicorn\s+app\.main:app\b)'
    }
)
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    Write-Host ("Stopped this repository's application process (PID {0})." -f $process.ProcessId)
}
if ($processes.Count -eq 0) {
    Write-Host 'No application process for this repository was running.'
}

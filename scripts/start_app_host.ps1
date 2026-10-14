[CmdletBinding()]
param(
    [string]$TaskName = "ClinicAntiviralTool",

    [string]$AppServiceAccount = "svc_clinic_tool",

    [string]$RepoPath,

    [ValidateRange(0, 65535)]
    [int]$Port = 0,

    [ValidateRange(1, 300)]
    [int]$WaitSeconds = 30
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "ClinicAntiviral.Onboarding.psm1") -Force

function Write-Pass {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Get-ConfiguredPort {
    param(
        [string]$Path,
        [int]$RequestedPort
    )

    if ($RequestedPort -gt 0) {
        return $RequestedPort
    }

    $envPath = Join-Path $Path ".env"
    if (Test-Path -LiteralPath $envPath -PathType Leaf) {
        $portLine = Get-Content -LiteralPath $envPath |
            Where-Object { $_ -match "^\s*PORT\s*=\s*\d+\s*$" } |
            Select-Object -First 1
        if ($portLine -match "^\s*PORT\s*=\s*(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }

    return 8000
}

function Test-LocalTcpPort {
    param(
        [int]$PortNumber,
        [int]$TimeoutMilliseconds = 500
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.ConnectAsync("127.0.0.1", $PortNumber)
        if (-not $connection.Wait($TimeoutMilliseconds)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent $PSScriptRoot
}
$repo = (Get-Item -LiteralPath $RepoPath -ErrorAction Stop).FullName

try {
    $localUser = Get-LocalUser -Name $AppServiceAccount -ErrorAction Stop
    if (-not $localUser.Enabled) {
        throw "Application service account is disabled: $AppServiceAccount"
    }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $expectedPython = Join-Path $repo ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $expectedPython -PathType Leaf)) {
        throw "The application Python executable is missing. Run onboard_app_host.ps1 first."
    }
    $expectedArguments = "-m app.startup --expected-account-sid {0}" -f $localUser.SID.Value
    Assert-ClinicTaskConfiguration `
        -Task $task `
        -ExpectedSid $localUser.SID.Value `
        -ExpectedRepoPath $repo `
        -ExpectedPythonPath $expectedPython `
        -ExpectedArguments $expectedArguments

    $portNumber = Get-ConfiguredPort -Path $repo -RequestedPort $Port
    Write-Host "Starting the application through Windows Task Scheduler."
    Write-Host ("Task: {0}" -f $TaskName)
    Write-Host ("Windows account: {0}\{1}" -f $env:COMPUTERNAME, $AppServiceAccount)
    Write-Host ("Local port: {0}" -f $portNumber)
    Write-Host "The HIS credential is read from this account's Windows Credential Manager store."

    if ($task.State -ne "Running") {
        Start-ScheduledTask -TaskName $TaskName
    }
    else {
        Write-Host "The scheduled task is already running."
    }

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        $currentTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (($null -ne $currentTask) -and $currentTask.State -eq "Running" -and (Test-LocalTcpPort -PortNumber $portNumber)) {
            Write-Pass ("Local listener check succeeded at http://127.0.0.1:{0}." -f $portNumber)
            exit 0
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "[FAIL] The application did not open the local port in time." -ForegroundColor Red
    if ($null -ne $taskInfo) {
        Write-Host ("Last run: {0}; result: {1}" -f $taskInfo.LastRunTime, $taskInfo.LastTaskResult)
    }
    Write-Host "Check the Task Scheduler history and the application log. No HIS files were changed by this launcher."
    exit 1
}
catch {
    Write-Host ("[FAIL] {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host "Run onboard_app_host.ps1 first, then store and verify the HIS credential under the application account."
    exit 1
}

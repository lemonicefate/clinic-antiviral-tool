[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$HisPath,

    [string]$AppServiceAccount = "svc_clinic_tool",

    [string]$TaskName = "ClinicAntiviralTool",

    [string]$RepoPath,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$PythonPath,

    [string]$AppDataPath = "C:\clinic-data\app-data",

    [string]$UploadedPath = "C:\clinic-data\uploaded",

    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [switch]$ConfigureFirewall,

    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "ClinicAntiviral.Onboarding.psm1") -Force

function Convert-SecureStringToPlainText {
    param([System.Security.SecureString]$SecureString)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Assert-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run onboard_app_host.ps1 from an elevated PowerShell window."
    }
}

function Grant-DirectoryAccess {
    param(
        [string]$Path,
        [string]$Account,
        [string]$Rights
    )

    & icacls.exe $Path "/grant" ("{0}:{1}" -f $Account, $Rights) "/T" "/C" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw ("icacls could not grant {0} access to {1}." -f $Rights, $Path)
    }
}

function Assert-LocalAccountIsSafe {
    param([Microsoft.PowerShell.Commands.LocalUser]$LocalUser)

    if (-not $LocalUser.Enabled) {
        throw ("Application service account is disabled: {0}" -f $LocalUser.Name)
    }
    $administrators = @(Get-LocalGroupMember -SID ([System.Security.Principal.SecurityIdentifier]"S-1-5-32-544") -ErrorAction SilentlyContinue)
    if ($administrators | Where-Object { $_.SID.Value -eq $LocalUser.SID.Value }) {
        throw ("Application service account must not be a member of local Administrators: {0}" -f $LocalUser.Name)
    }
}

if ($HisPath -notmatch "^\\\\[^\\]+\\[^\\]+") {
    throw "HisPath must be an explicit UNC path such as \\HIS01\HISROOT. Do not use a mapped drive."
}
if ($AppServiceAccount -match "[\\/\s]") {
    throw "AppServiceAccount must be a local account name without a host prefix."
}

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent $PSScriptRoot
}
$repo = (Get-Item -LiteralPath $RepoPath).FullName
$envPath = Join-Path $repo ".env"
$requirementsPath = Join-Path $repo "requirements.txt"
$venvPath = Join-Path $repo ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
Assert-Elevated
$pythonEnvironment = Assert-ClinicPythonEnvironment -PythonPath $PythonPath -VenvPath $venvPath
$PythonPath = $pythonEnvironment.Path
$credentialTarget = Get-ClinicCredentialTarget -HisPath $HisPath

Write-Host "Application host onboarding"
Write-Host ("Repository: {0}" -f $repo)
Write-Host ("HIS UNC path: {0}" -f $HisPath)
Write-Host ""
Write-Host "This script changes the application host only. It does not create or change an HIS user, share, or ACL."

try {
    $qualifiedAccount = ("{0}\{1}" -f $env:COMPUTERNAME, $AppServiceAccount)
    $localUser = Get-LocalUser -Name $AppServiceAccount -ErrorAction SilentlyContinue
    if ($null -eq $localUser) {
        Write-Host ("Create local application account {0}." -f $AppServiceAccount)
        $securePassword = Read-Host "Enter the application account password" -AsSecureString
        if ($null -eq $securePassword -or $securePassword.Length -eq 0) {
            throw "The application account password cannot be empty. No account was created."
        }
        $localUser = New-LocalUser -Name $AppServiceAccount -Password $securePassword -Description "Clinic antiviral tool application task"
        $usersMembers = @(Get-LocalGroupMember -SID ([System.Security.Principal.SecurityIdentifier]"S-1-5-32-545") -ErrorAction SilentlyContinue)
        if (-not ($usersMembers | Where-Object { $_.SID.Value -eq $localUser.SID.Value })) {
            Add-LocalGroupMember -SID ([System.Security.Principal.SecurityIdentifier]"S-1-5-32-545") -Member $AppServiceAccount
        }
    }
    else {
        Write-Host ("Use existing local application account {0}." -f $AppServiceAccount)
        Assert-LocalAccountIsSafe -LocalUser $localUser
        $securePassword = Read-Host "Enter the existing application account password for Task Scheduler" -AsSecureString
    }
    Assert-LocalAccountIsSafe -LocalUser $localUser
    if ($null -eq $securePassword -or $securePassword.Length -eq 0) {
        throw "The application account password cannot be empty."
    }
    $applicationCredential = New-Object System.Management.Automation.PSCredential($qualifiedAccount, $securePassword)
    Assert-ClinicPythonCanRunAsUser -PythonPath $PythonPath -Credential $applicationCredential

    $plainPassword = Convert-SecureStringToPlainText -SecureString $securePassword
    if ([string]::IsNullOrEmpty($plainPassword)) {
        throw "The application account password cannot be empty."
    }

    New-Item -ItemType Directory -Force -Path $AppDataPath, $UploadedPath | Out-Null

    if (-not (Test-Path -LiteralPath $venvPath)) {
        Write-Host "Create Python 3.12 virtual environment."
        & $PythonPath -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12 virtual environment creation failed."
        }
    }
    [void](Assert-ClinicPythonEnvironment -PythonPath $PythonPath -VenvPath $venvPath)
    Grant-DirectoryAccess -Path $repo -Account $qualifiedAccount -Rights "(OI)(CI)RX"
    Assert-ClinicPythonCanRunAsUser -PythonPath $venvPython -Credential $applicationCredential
    if (-not $SkipDependencyInstall) {
        Write-Host "Install Python dependencies."
        & $venvPython -m pip install -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw "Python dependency installation failed."
        }
    }

    Set-DotEnvValue -Path $envPath -Name "HIS_MIRROR_PATH" -Value $HisPath
    Set-DotEnvValue -Path $envPath -Name "APP_DATA_PATH" -Value $AppDataPath
    Set-DotEnvValue -Path $envPath -Name "UPLOADED_PATH" -Value $UploadedPath
    Set-DotEnvValue -Path $envPath -Name "SMIS_TEMPLATE_PATH" -Value "official-template\smis_report.xlsx" -OnlyIfMissing
    Set-DotEnvValue -Path $envPath -Name "HOST" -Value "0.0.0.0"
    Set-DotEnvValue -Path $envPath -Name "PORT" -Value ([string]$Port)

    Grant-DirectoryAccess -Path $AppDataPath -Account $qualifiedAccount -Rights "(OI)(CI)M"
    Grant-DirectoryAccess -Path $UploadedPath -Account $qualifiedAccount -Rights "(OI)(CI)M"

    $actionParameters = @{
        Execute = $venvPython
        Argument = ("-m app.startup --expected-account-sid {0}" -f $localUser.SID.Value)
        WorkingDirectory = $repo
    }
    $action = New-ScheduledTaskAction @actionParameters
    $trigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 1)
    $settings = New-ClinicTaskSettings

    $registrationParameters = @{
        TaskName = $TaskName
        Action = $action
        Trigger = $trigger
        Settings = $settings
        User = $qualifiedAccount
        Password = $plainPassword
        RunLevel = "Limited"
        Description = "Clinic antiviral tool. Reads HIS through the configured read-only UNC path."
        Force = $true
    }
    Register-ScheduledTask @registrationParameters | Out-Null

    if ($ConfigureFirewall) {
        $ruleName = "Clinic Antiviral Tool TCP {0}" -f $Port
        $firewallRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if ($null -eq $firewallRule) {
            $firewallParameters = @{
                DisplayName = $ruleName
                Direction = "Inbound"
                Action = "Allow"
                Protocol = "TCP"
                LocalPort = $Port
                Profile = "Private"
                Description = "Clinic LAN access to the antiviral tool. This is host firewall policy, not application authentication."
            }
            New-NetFirewallRule @firewallParameters | Out-Null
            Write-Host ("[PASS] Private-profile firewall rule created for TCP {0}." -f $Port) -ForegroundColor Green
        }
        else {
            Write-Host ("[NOTE] Firewall rule already exists: {0}." -f $ruleName) -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "[NOTE] No firewall rule was changed. Use -ConfigureFirewall after confirming the app host network profile is Private." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "[PASS] Application host build completed. HIS credential and read-only access verification remain pending." -ForegroundColor Green
    Write-Host "The startup preflight will keep uvicorn stopped until this task account can read the required HIS tables."
    Write-Host ("Task: {0}" -f $TaskName)
    Write-Host ("Local application account: {0}" -f $qualifiedAccount)
    Write-Host "The HIS credential is not stored by this elevated script. Store it once under the application account."
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host ("1. runas /user:{0} /profile powershell.exe" -f $qualifiedAccount)
    Write-Host ("2. .\scripts\store_his_credential.ps1 -Target '{0}' -RemoteUser '<REAL_HIS_HOST>\svc_clinic_his_ro' -ExpectedAccount '{1}'" -f $credentialTarget, $qualifiedAccount)
    Write-Host ("3. .\scripts\verify_his_access.ps1 -HisPath '{0}'" -f $HisPath)
    Write-Host "4. .\scripts\start.bat"
}
finally {
    if ($null -ne $applicationCredential) {
        $applicationCredential = $null
    }
    if ($null -ne $securePassword) {
        $securePassword.Dispose()
    }
    if ($null -ne $plainPassword) {
        $plainPassword = $null
    }
}

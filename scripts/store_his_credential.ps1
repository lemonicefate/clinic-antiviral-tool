[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern("^[^\\/:\s]+$")]
    [string]$Target,

    [Parameter(Mandatory = $true, Position = 1)]
    [ValidateNotNullOrEmpty()]
    [string]$RemoteUser,

    [string]$ExpectedAccount = "svc_clinic_tool"
)

$ErrorActionPreference = "Stop"

$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$currentAccount = ($currentIdentity -split "\\")[-1]
$expectedLeaf = ($ExpectedAccount -split "\\")[-1]
if ($ExpectedAccount -and $currentAccount -ine $expectedLeaf) {
    throw ("Run this script as the application service account {0}. Current identity: {1}" -f $ExpectedAccount, $currentIdentity)
}

if ($RemoteUser -notmatch "\\") {
    Write-Warning "RemoteUser does not contain a host prefix. For a workgroup HIS host use HIS_HOST\svc_clinic_his_ro."
}

Write-Host ("Storing the HIS credential for target {0}." -f $Target)
Write-Host "Windows will prompt for the password. The password is not a script argument."
Write-Host ""

# Do not add /pass. cmdkey prompts on the interactive console and stores the
# credential in the current Windows user's credential store.
& cmdkey.exe ("/add:{0}" -f $Target) ("/user:{0}" -f $RemoteUser)
if ($LASTEXITCODE -ne 0) {
    throw "cmdkey could not store the HIS credential. No application configuration was changed."
}

Write-Host "[PASS] HIS credential was stored for this Windows account." -ForegroundColor Green
Write-Host "Next, run verify_his_access.ps1 under this same account."

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^[^\\/:\s]+$')]
    [string]$Target,

    [Parameter(Mandatory = $true, Position = 1)]
    [ValidatePattern('^[^\\]+\\[^\\]+$')]
    [string]$RemoteUser,

    [string]$ExpectedAccount = 'svc_clinic_tool'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ClinicAntiviral.Onboarding.psm1') -Force

$expectedSid = Get-ClinicLocalAccountSid -ExpectedAccount $ExpectedAccount
Write-Host ("Storing the HIS credential for target {0}." -f $Target)
Write-Host "Enter the password only in the secure prompt. It is not a script argument or configuration value."
Save-ClinicHisCredential `
    -Target $Target `
    -RemoteUser $RemoteUser `
    -ExpectedSid $expectedSid

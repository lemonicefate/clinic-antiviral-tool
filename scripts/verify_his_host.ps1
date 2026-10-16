[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$HisRootPath,

    [string]$ReadonlyAccount = "svc_clinic_his_ro",

    [string]$ShareName = "",

    [string[]]$RequiredTables = @("CH012M1", "CH011M1", "PD011M1")
)

$ErrorActionPreference = "Stop"
$script:VerificationFailed = $false
$script:AuthorizationContext = [PSCustomObject]@{ Sids = @(); Complete = $false }
Import-Module (Join-Path $PSScriptRoot "ClinicAntiviral.Onboarding.psm1") -Force

function Write-Pass {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Write-Note {
    param([string]$Message)
    Write-Host "[NOTE] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    $script:VerificationFailed = $true
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Find-TableFile {
    param(
        [System.IO.DirectoryInfo]$Root,
        [string]$TableName
    )

    $locations = @($Root.FullName, (Join-Path $Root.FullName "DATA"))
    foreach ($location in $locations) {
        $candidate = Join-Path $location ("{0}.DBF" -f $TableName)
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return Get-Item -LiteralPath $candidate
        }
    }
    return $null
}

function Test-ReadOnlyAclForPath {
    param(
        [string]$Path,
        [string]$Description
    )

    try {
        $acl = Get-Acl -LiteralPath $Path
        $decision = Get-ClinicReadOnlyAccessDecision `
            -Rules @($acl.Access) `
            -ApplicableSids $script:AuthorizationContext.Sids `
            -PrincipalGraphComplete $script:AuthorizationContext.Complete `
            -Kind FileSystem
        if ($decision.Allowed) {
            Write-Pass ("Read-only ACL metadata is proven for this resource: {0}" -f $Description)
        }
        else {
            Write-Fail ("The NTFS read-only grant is not proven for {0}: {1}" -f $Description, $decision.Reason)
        }
    }
    catch {
        Write-Fail ("The NTFS ACL could not be inspected: {0}" -f $Description)
    }
}

Write-Host "HIS host read-only verification"
Write-Host "This script reads account, share, ACL, and table metadata only."
Write-Host "It does not create users, shares, permissions, or files."

try {
    $root = Get-Item -LiteralPath $HisRootPath
    if (-not $root.PSIsContainer) {
        throw "HisRootPath is not a directory: $HisRootPath"
    }
}
catch {
    Write-Fail "HIS root cannot be read: $HisRootPath"
    exit 1
}

try {
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem
    if ($computer.PartOfDomain) {
        Write-Note "This host is domain joined. Confirm the approved domain account and policy before production use."
    }
    else {
        Write-Pass ("HIS host is in workgroup {0}." -f $computer.Domain)
    }
}
catch {
    Write-Note "Workgroup status could not be read. Continue only after a local administrator confirms it."
}

try {
    $localUser = Get-LocalUser -Name $ReadonlyAccount -ErrorAction SilentlyContinue
    if ($null -eq $localUser) {
        Write-Fail ("Local read-only account does not exist: {0}" -f $ReadonlyAccount)
    }
    elseif (-not $localUser.Enabled) {
        Write-Fail ("Local read-only account is disabled: {0}" -f $ReadonlyAccount)
    }
    else {
        Write-Pass ("Local read-only account exists and is enabled: {0}" -f $ReadonlyAccount)
    }

    if ($null -ne $localUser) {
        $script:AuthorizationContext = Get-ClinicAuthorizationContext -AccountSid $localUser.SID.Value
        if (-not $script:AuthorizationContext.Complete) {
            Write-Fail "Local group membership could not be fully resolved. Ask the HIS administrator to confirm the account's access."
        }
        elseif ($script:AuthorizationContext.Sids -contains "S-1-5-32-544") {
            Write-Fail ("Read-only account is a member of the local Administrators group: {0}" -f $ReadonlyAccount)
        }
        else {
            Write-Pass "Read-only account is not a member of local Administrators through a resolved local group."
        }
    }
}
catch {
    Write-Fail "The local account or local group membership could not be inspected."
}

$share = $null
try {
    if ($ShareName) {
        $share = Get-SmbShare -Name $ShareName -ErrorAction Stop
    }
    else {
        $matchingShares = @(
            Get-SmbShare -ErrorAction Stop | Where-Object {
                if (-not $_.Path) { return $false }
                try {
                    $sharePath = (Get-Item -LiteralPath $_.Path -ErrorAction Stop).FullName
                    return $sharePath.TrimEnd('\') -ieq $root.FullName.TrimEnd('\')
                }
                catch {
                    return $false
                }
            }
        )
        if ($matchingShares.Count -eq 0) {
            Write-Fail ("No SMB share points to HIS root: {0}" -f $root.FullName)
        }
        else {
            if ($matchingShares.Count -gt 1) {
                Write-Note ("More than one SMB share points to the HIS root. Use -ShareName to verify one explicitly: {0}" -f (($matchingShares | ForEach-Object Name) -join ", "))
            }
            $share = $matchingShares[0]
        }
    }

    if ($null -ne $share) {
        if ($share.Path) {
            $sharePath = (Get-Item -LiteralPath $share.Path).FullName
            if ($sharePath.TrimEnd('\') -ine $root.FullName.TrimEnd('\')) {
                Write-Fail ("SMB share does not point to the requested HIS root: {0}" -f $share.Name)
            }
            else {
                Write-Pass ("SMB share points to the requested HIS root: {0}" -f $share.Name)
            }
        }

        $shareAccess = @(Get-SmbShareAccess -Name $share.Name -ErrorAction Stop)
        $shareDecision = Get-ClinicReadOnlyAccessDecision `
            -Rules $shareAccess `
            -ApplicableSids $script:AuthorizationContext.Sids `
            -PrincipalGraphComplete $script:AuthorizationContext.Complete `
            -Kind Share
        if ($shareDecision.Allowed) {
            Write-Pass "Read-only SMB ACL metadata is proven for the selected HIS share."
        }
        else {
            Write-Fail ("The SMB read-only grant is not proven for the selected HIS share: {0}" -f $shareDecision.Reason)
        }
    }
}
catch {
    Write-Fail "The SMB share or share permissions could not be inspected."
}

Test-ReadOnlyAclForPath -Path $root.FullName -Description "HIS root"
$dataDirectory = Join-Path $root.FullName "DATA"
if (Test-Path -LiteralPath $dataDirectory -PathType Container) {
    Test-ReadOnlyAclForPath -Path $dataDirectory -Description "HIS DATA directory"
}

foreach ($table in $RequiredTables) {
    $tableFile = Find-TableFile -Root $root -TableName $table
    if ($null -eq $tableFile) {
        Write-Fail ("Required HIS table is missing from the root or DATA directory: {0}.DBF" -f $table)
    }
    else {
        Write-Pass ("Required HIS table is present: {0}" -f $tableFile.FullName)
        Test-ReadOnlyAclForPath -Path $tableFile.FullName -Description ("required table {0}" -f $tableFile.Name)
    }
}

$optionalInventory = Find-TableFile -Root $root -TableName "H_INV"
if ($null -eq $optionalInventory) {
    Write-Note "Optional HIS table is not present: H_INV.DBF. Continue only if the configured medication mapping does not need it."
}
else {
    Write-Pass ("Optional HIS table is present: {0}" -f $optionalInventory.FullName)
    Test-ReadOnlyAclForPath -Path $optionalInventory.FullName -Description ("optional table {0}" -f $optionalInventory.Name)
}

Write-Host ""
if ($script:VerificationFailed) {
    Write-Host "[FAIL] HIS host verification failed. No HIS settings were changed." -ForegroundColor Red
    exit 1
}

Write-Host "[PASS] HIS host verification completed. No HIS settings were changed." -ForegroundColor Green
exit 0

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$HisPath,

    [string]$ExpectedAccount = "svc_clinic_tool",

    [string[]]$RequiredTables = @("CH012M1", "CH011M1", "PD011M1")
)

$ErrorActionPreference = "Stop"
$script:VerificationFailed = $false

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

function Test-ReadOnlyFileOpen {
    param([System.IO.FileInfo]$File)

    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $File.FullName,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite
        )
        if ($stream.Length -gt 0) {
            $buffer = New-Object byte[] 1
            [void]$stream.Read($buffer, 0, 1)
        }
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

Write-Host "Application host HIS access verification"
Write-Host "This script opens required files for read only. It never writes to HIS."

$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$currentAccount = ($currentIdentity -split "\\")[-1]
Write-Host ("Current Windows identity: {0}" -f $currentIdentity)
if ($ExpectedAccount -and $currentAccount -ine (($ExpectedAccount -split "\\")[-1])) {
    Write-Fail ("Run this check as the application service account: {0}" -f $ExpectedAccount)
}
else {
    Write-Pass "The verification is running under the expected application account."
}

if ($HisPath -notmatch "^\\\\[^\\]+\\[^\\]+") {
    Write-Fail "HisPath must be an explicit UNC path such as \\HIS01\HISROOT. Do not use a mapped drive."
    exit 1
}

try {
    $root = Get-Item -LiteralPath $HisPath
    if (-not $root.PSIsContainer) {
        throw "UNC path is not a directory."
    }
    Write-Pass ("UNC path can be listed: {0}" -f $root.FullName)
}
catch {
    Write-Fail "The application account cannot list the HIS UNC path. Check the workgroup credential and SMB firewall."
    exit 1
}

foreach ($table in $RequiredTables) {
    $tableFile = Find-TableFile -Root $root -TableName $table
    if ($null -eq $tableFile) {
        Write-Fail ("Required HIS table is missing from the root or DATA directory: {0}.DBF" -f $table)
        continue
    }
    if (Test-ReadOnlyFileOpen -File $tableFile) {
        Write-Pass ("Required HIS table can be opened for read: {0}" -f $tableFile.Name)
    }
    else {
        Write-Fail ("Required HIS table cannot be opened for read: {0}" -f $tableFile.FullName)
    }
}

$optionalInventory = Find-TableFile -Root $root -TableName "H_INV"
if ($null -eq $optionalInventory) {
    Write-Note "Optional HIS table is not present: H_INV.DBF."
}
elseif (Test-ReadOnlyFileOpen -File $optionalInventory) {
    Write-Pass ("Optional HIS table can be opened for read: {0}" -f $optionalInventory.Name)
}
else {
    Write-Fail ("Optional HIS table exists but cannot be opened for read: {0}" -f $optionalInventory.FullName)
}

Write-Host ""
if ($script:VerificationFailed) {
    Write-Host "[FAIL] Application host HIS access verification failed. No HIS files were changed." -ForegroundColor Red
    exit 1
}

Write-Host "[PASS] Application host HIS access verification completed. No HIS files were changed." -ForegroundColor Green
exit 0

Set-StrictMode -Version Latest

if (-not ('ClinicAntiviralCredentialNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ClinicAntiviralCredentialNative
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NativeCredential
    {
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public long LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    [DllImport("Advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWrite(ref NativeCredential credential, int flags);

    [DllImport("Advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(string target, int type, int flags, out IntPtr credential);

    [DllImport("Advapi32.dll", EntryPoint = "CredFree")]
    private static extern void CredFree(IntPtr buffer);

    public static bool Write(string target, string userName, IntPtr blob, int blobSize, int type, int persist, out int errorCode)
    {
        var credential = new NativeCredential
        {
            Flags = 0,
            Type = type,
            TargetName = target,
            Comment = null,
            LastWritten = 0,
            CredentialBlobSize = blobSize,
            CredentialBlob = blob,
            Persist = persist,
            AttributeCount = 0,
            Attributes = IntPtr.Zero,
            TargetAlias = null,
            UserName = userName
        };
        var saved = CredWrite(ref credential, 0);
        errorCode = saved ? 0 : Marshal.GetLastWin32Error();
        return saved;
    }

    public static bool Exists(string target, int type, out int errorCode)
    {
        IntPtr credential;
        var found = CredRead(target, type, 0, out credential);
        errorCode = found ? 0 : Marshal.GetLastWin32Error();
        if (credential != IntPtr.Zero)
        {
            CredFree(credential);
        }
        return found;
    }
}
'@ -ErrorAction Stop
}

function Set-DotEnvValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[A-Za-z_][A-Za-z0-9_]*$')]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value,

        [switch]$OnlyIfMissing
    )

    if ($Value -match '[\r\n]') {
        throw ("Configuration value contains a newline: {0}" -f $Name)
    }

    $utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
    $lines = New-Object 'System.Collections.Generic.List[string]'
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        try {
            foreach ($line in [System.IO.File]::ReadAllLines($Path, $utf8Strict)) {
                $lines.Add($line)
            }
        }
        catch [System.Text.DecoderFallbackException] {
            throw ("Configuration file is not valid UTF-8 and was left unchanged: {0}" -f $Path)
        }
    }

    $assignmentPattern = '^\s*{0}\s*=' -f [Regex]::Escape($Name)
    foreach ($line in $lines) {
        if ($line -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=[^\r\n]*[A-Za-z_][A-Za-z0-9_]*\s*=') {
            throw ("Configuration file appears to contain joined settings and was left unchanged: {0}. Recreate it from confirmed values." -f $Path)
        }
    }

    $matchingIndexes = New-Object 'System.Collections.Generic.List[int]'
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match $assignmentPattern) {
            $matchingIndexes.Add($index)
        }
    }
    if ($OnlyIfMissing -and $matchingIndexes.Count -gt 0) {
        return
    }

    $updated = New-Object 'System.Collections.Generic.List[string]'
    $replacement = "{0}={1}" -f $Name, $Value
    $firstMatch = if ($matchingIndexes.Count -gt 0) { $matchingIndexes[0] } else { -1 }
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($index -eq $firstMatch) {
            $updated.Add($replacement)
        }
        elseif ($lines[$index] -notmatch $assignmentPattern) {
            $updated.Add($lines[$index])
        }
    }
    if ($firstMatch -lt 0) {
        $updated.Add($replacement)
    }

    [System.IO.File]::WriteAllLines($Path, $updated.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
}

function ConvertTo-ClinicSecurityIdentifier {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PrincipalUserId)

    if ($PrincipalUserId -match '^S-\d-\d+(-\d+)+$') {
        return ([System.Security.Principal.SecurityIdentifier]$PrincipalUserId).Value
    }

    try {
        $account = New-Object System.Security.Principal.NTAccount($PrincipalUserId)
        return $account.Translate([System.Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        throw ("Could not resolve the scheduled-task principal to a SID: {0}" -f $PrincipalUserId)
    }
}

function New-ClinicTaskSettings {
    [CmdletBinding()]
    param()

    return New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
}

function ConvertTo-ClinicTimeSpan {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [TimeSpan]) {
        return $Value
    }
    try {
        return [System.Xml.XmlConvert]::ToTimeSpan([string]$Value)
    }
    catch {
        try {
            return [TimeSpan]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture)
        }
        catch {
            return $null
        }
    }
}

function Assert-ClinicTaskConfiguration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Task,
        [Parameter(Mandatory = $true)][string]$ExpectedSid,
        [Parameter(Mandatory = $true)][string]$ExpectedRepoPath,
        [Parameter(Mandatory = $true)][string]$ExpectedPythonPath,
        [Parameter(Mandatory = $true)][string]$ExpectedArguments
    )

    $settings = $Task.Settings
    if ($null -eq $settings -or $null -eq $settings.Enabled -or -not [bool]$settings.Enabled) {
        throw "Scheduled task is disabled or its enabled state cannot be confirmed. The task was not started."
    }
    if (-not $settings.StartWhenAvailable) {
        throw "Scheduled task does not retain its start-when-available setting. The task was not started."
    }
    if ([int]$settings.RestartCount -ne 3 -or (ConvertTo-ClinicTimeSpan $settings.RestartInterval) -ne (New-TimeSpan -Minutes 1)) {
        throw "Scheduled task does not have the expected failure-restart policy. The task was not started."
    }
    if ((ConvertTo-ClinicTimeSpan $settings.ExecutionTimeLimit) -ne [TimeSpan]::Zero) {
        throw "Scheduled task has an execution time limit or the limit cannot be confirmed. The task was not started."
    }

    $principal = $Task.Principal
    if ($null -eq $principal -or [string]::IsNullOrWhiteSpace([string]$principal.UserId)) {
        throw "Scheduled task principal cannot be confirmed. The task was not started."
    }
    $principalSid = ConvertTo-ClinicSecurityIdentifier -PrincipalUserId ([string]$principal.UserId)
    if ($principalSid -ne $ExpectedSid) {
        throw ("Scheduled task principal SID is {0}, not the expected application account SID {1}. The task was not started." -f $principalSid, $ExpectedSid)
    }
    if ([string]$principal.LogonType -ne 'Password') {
        throw ("Scheduled task logon type is {0}; a Password logon is required for HIS network access. The task was not started." -f $principal.LogonType)
    }

    $actions = @($Task.Actions)
    if ($actions.Count -ne 1 -or $null -eq $actions[0]) {
        throw "Scheduled task must contain exactly one application action. The task was not started."
    }
    $action = $actions[0]
    $expectedPython = [IO.Path]::GetFullPath($ExpectedPythonPath)
    $actualPython = [Environment]::ExpandEnvironmentVariables([string]$action.Execute)
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetFullPath($actualPython), $expectedPython)) {
        throw ("Scheduled task executable is {0}, not {1}. The task was not started." -f $actualPython, $expectedPython)
    }
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals(([string]$action.Arguments).Trim(), $ExpectedArguments.Trim())) {
        throw "Scheduled task action arguments are not the expected startup preflight. The task was not started."
    }
    $expectedRepo = [IO.Path]::GetFullPath($ExpectedRepoPath)
    $workingDirectory = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$action.WorkingDirectory))
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($workingDirectory, $expectedRepo)) {
        throw ("Scheduled task working directory is {0}, not {1}. The task was not started." -f $workingDirectory, $expectedRepo)
    }

    $hasStartupTrigger = $false
    foreach ($trigger in @($Task.Triggers)) {
        if ($null -eq $trigger) { continue }
        $className = [string]$trigger.CimClass.CimClassName
        if ([string]::IsNullOrWhiteSpace($className)) {
            $className = [string]$trigger.CimSystemProperties.ClassName
        }
        if ($className -match '(?i)BootTrigger') {
            $hasStartupTrigger = $true
            break
        }
    }
    if (-not $hasStartupTrigger) {
        throw "Scheduled task has no Windows startup trigger. The task was not started."
    }
}

function Get-ClinicPythonRuntimeInfo {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [scriptblock]$RuntimeProbe
    )

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw ("The configured Python interpreter does not exist: {0}" -f $PythonPath)
    }
    $resolvedPath = (Get-Item -LiteralPath $PythonPath).FullName
    try {
        if ($null -ne $RuntimeProbe) {
            $runtime = & $RuntimeProbe $resolvedPath
        }
        else {
            $probeCode = @'
import os
import sys
import sysconfig
import encodings
import venv
import ensurepip

stdlib = os.path.realpath(sysconfig.get_path('stdlib'))
normalize = lambda value: os.path.normcase(os.path.realpath(value))
modules = (encodings, venv, ensurepip)
try:
    stdlib_valid = os.path.isdir(stdlib) and all(
        os.path.commonpath([normalize(stdlib), normalize(module.__file__)]) == normalize(stdlib)
        for module in modules
    )
except (OSError, TypeError, ValueError):
    stdlib_valid = False

print('CLINIC_VERSION=%d.%d' % sys.version_info[:2])
print('CLINIC_BASE=' + os.path.realpath(sys.base_prefix))
print('CLINIC_STDLIB=' + stdlib)
print('CLINIC_STDLIB_VALID=' + ('true' if stdlib_valid else 'false'))
'@
            $probeOutput = @(& $resolvedPath -c $probeCode 2>&1)
            if ($LASTEXITCODE -ne 0 -or $probeOutput.Count -lt 4) {
                throw "Python did not return a successful runtime and standard-library probe."
            }
            $versionLine = $probeOutput | Where-Object { [string]$_ -match '^CLINIC_VERSION=\d+\.\d+$' } | Select-Object -First 1
            $baseLine = $probeOutput | Where-Object { [string]$_ -match '^CLINIC_BASE=.+$' } | Select-Object -First 1
            $stdlibLine = $probeOutput | Where-Object { [string]$_ -match '^CLINIC_STDLIB=.+$' } | Select-Object -First 1
            $stdlibValidLine = $probeOutput | Where-Object { [string]$_ -match '^CLINIC_STDLIB_VALID=(true|false)$' } | Select-Object -First 1
            if ($null -eq $versionLine -or $null -eq $baseLine -or $null -eq $stdlibLine -or $null -eq $stdlibValidLine) {
                throw "Python did not return its version, base interpreter, and standard-library markers."
            }
            if ([string]$stdlibValidLine -ne 'CLINIC_STDLIB_VALID=true') {
                throw "Python's standard library, venv module, or ensurepip module is incomplete or mismatched."
            }
            $runtime = [PSCustomObject]@{
                Version = ([string]$versionLine -replace '^CLINIC_VERSION=', '')
                BasePrefix = ([string]$baseLine -replace '^CLINIC_BASE=', '')
                StdlibPath = ([string]$stdlibLine -replace '^CLINIC_STDLIB=', '')
                StdlibValid = $true
            }
        }
    }
    catch {
        throw ("The configured Python interpreter failed its version, base-path, or standard-library check: {0}" -f $resolvedPath)
    }

    if ($null -eq $runtime -or [string]::IsNullOrWhiteSpace([string]$runtime.Version) -or [string]::IsNullOrWhiteSpace([string]$runtime.BasePrefix) -or [string]::IsNullOrWhiteSpace([string]$runtime.StdlibPath) -or $null -eq $runtime.StdlibValid -or -not [bool]$runtime.StdlibValid) {
        throw ("Python did not return a usable runtime and standard-library identity: {0}" -f $resolvedPath)
    }
    return [PSCustomObject]@{
        Path = $resolvedPath
        Version = [string]$runtime.Version
        BasePrefix = [IO.Path]::GetFullPath([string]$runtime.BasePrefix).TrimEnd('\')
        StdlibPath = [IO.Path]::GetFullPath([string]$runtime.StdlibPath).TrimEnd('\')
    }
}

function Assert-ClinicPythonEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string]$VenvPath,
        [scriptblock]$RuntimeProbe
    )

    if ([IO.Path]::GetExtension($PythonPath) -ine '.exe') {
        throw ("PythonPath must point to an installed python.exe: {0}" -f $PythonPath)
    }
    $runtime = Get-ClinicPythonRuntimeInfo -PythonPath $PythonPath -RuntimeProbe $RuntimeProbe
    if ($runtime.Version -ne '3.12') {
        throw ("The configured shared Python must be version 3.12; {0} reports {1}." -f $runtime.Path, $runtime.Version)
    }

    if (Test-Path -LiteralPath $VenvPath) {
        if (-not (Test-Path -LiteralPath $VenvPath -PathType Container)) {
            throw ("The configured venv path is not a directory: {0}. Recreate only the venv after reviewing it." -f $VenvPath)
        }
        $venvPython = Join-Path $VenvPath 'Scripts\python.exe'
        $venvConfig = Join-Path $VenvPath 'pyvenv.cfg'
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or -not (Test-Path -LiteralPath $venvConfig -PathType Leaf)) {
            throw ("The existing venv is incomplete: {0}. Review it and recreate only .venv; application data was left untouched." -f $VenvPath)
        }
        $configText = [System.IO.File]::ReadAllText($venvConfig, (New-Object System.Text.UTF8Encoding($false, $true)))
        $homeMatch = [Regex]::Match($configText, '(?m)^\s*home\s*=\s*(.+?)\s*$')
        if (-not $homeMatch.Success) {
            throw ("The existing venv does not identify its base Python: {0}. Recreate only .venv after review." -f $VenvPath)
        }
        $venvBase = [IO.Path]::GetFullPath($homeMatch.Groups[1].Value).TrimEnd('\')
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($venvBase, $runtime.BasePrefix)) {
            throw ("The existing venv base Python is {0}, not {1}. Recreate only .venv with the selected shared Python 3.12; application data was left untouched." -f $venvBase, $runtime.BasePrefix)
        }
        $venvRuntime = Get-ClinicPythonRuntimeInfo -PythonPath $venvPython -RuntimeProbe $RuntimeProbe
        if ($venvRuntime.Version -ne '3.12' -or -not [StringComparer]::OrdinalIgnoreCase.Equals($venvRuntime.BasePrefix, $runtime.BasePrefix)) {
            throw ("The existing venv interpreter does not match the selected shared Python 3.12: {0}. Recreate only .venv; application data was left untouched." -f $venvPython)
        }
    }

    return $runtime
}

function Assert-ClinicPythonCanRunAsUser {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][System.Management.Automation.PSCredential]$Credential,
        [scriptblock]$ProcessRunner
    )

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw ("The Python executable does not exist: {0}" -f $PythonPath)
    }
    $resolvedPath = (Get-Item -LiteralPath $PythonPath).FullName
    $arguments = '-c "import sys; assert sys.version_info[:2] == (3, 12)"'
    try {
        if ($null -ne $ProcessRunner) {
            $process = & $ProcessRunner $resolvedPath $Credential $arguments
        }
        else {
            $process = Start-Process `
                -FilePath $resolvedPath `
                -ArgumentList $arguments `
                -Credential $Credential `
                -Wait `
                -PassThru `
                -WindowStyle Hidden `
                -ErrorAction Stop
        }
    }
    catch {
        $launchException = $_.Exception
        $nativeException = $launchException
        while ($null -ne $nativeException -and $nativeException -isnot [System.ComponentModel.Win32Exception]) {
            $nativeException = $nativeException.InnerException
        }
        $launchDetail = $launchException.Message
        if ($null -ne $nativeException) {
            $launchDetail = ("Win32 error {0}: {1}" -f $nativeException.NativeErrorCode, $nativeException.Message)
        }
        $message = ("The application account could not launch the configured Python interpreter: {0}. {1}" -f $resolvedPath, $launchDetail)
        throw [System.InvalidOperationException]::new($message, $launchException)
    }
    if ($null -eq $process -or [int]$process.ExitCode -ne 0) {
        throw ("The application account could not run Python 3.12 at {0}. Check its runtime permissions before continuing." -f $resolvedPath)
    }
}

function Get-ClinicLocalAccountSid {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ExpectedAccount)

    $parts = $ExpectedAccount -split '\\', 2
    if ($parts.Count -eq 2 -and $parts[0] -ine $env:COMPUTERNAME) {
        throw ("Expected account is not local to this computer: {0}" -f $ExpectedAccount)
    }
    $accountName = $parts[$parts.Count - 1]
    try {
        $localUser = Get-LocalUser -Name $accountName -ErrorAction Stop
    }
    catch {
        throw ("Expected local Windows account was not found: {0}" -f $ExpectedAccount)
    }
    return $localUser.SID.Value
}

function Assert-ClinicCurrentAccountSid {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedSid,
        [string]$CurrentSid
    )

    if ([string]::IsNullOrWhiteSpace($CurrentSid)) {
        $CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    }
    if ($CurrentSid -ne $ExpectedSid) {
        throw ("This operation must run as the expected application account SID {0}. Current account SID is {1}." -f $ExpectedSid, $CurrentSid)
    }
}

function Get-ClinicCredentialTarget {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$HisPath)

    $match = [Regex]::Match($HisPath, '^\\\\(?<host>[^\\]+)\\[^\\]+')
    if (-not $match.Success) {
        throw "HIS path must be an explicit UNC path before deriving a Credential Manager target."
    }
    return $match.Groups['host'].Value
}

function Write-ClinicCredentialNative {
    param(
        [string]$Target,
        [string]$RemoteUser,
        [IntPtr]$Blob,
        [int]$BlobSize,
        [int]$CredentialType,
        [int]$Persist
    )

    $nativeError = 0
    $saved = [ClinicAntiviralCredentialNative]::Write(
        $Target,
        $RemoteUser,
        $Blob,
        $BlobSize,
        $CredentialType,
        $Persist,
        [ref]$nativeError
    )
    return [PSCustomObject]@{ Success = [bool]$saved; ErrorCode = [int]$nativeError }
}

function Test-ClinicCredentialEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidatePattern('^[^\\/:\s]+$')][string]$Target,
        [scriptblock]$CredentialReader
    )

    if ($null -ne $CredentialReader) {
        $result = & $CredentialReader $Target 2
        return [PSCustomObject]@{ Exists = [bool]$result.Exists; ErrorCode = [int]$result.ErrorCode }
    }

    $nativeError = 0
    $found = [ClinicAntiviralCredentialNative]::Exists($Target, 2, [ref]$nativeError)
    return [PSCustomObject]@{ Exists = [bool]$found; ErrorCode = [int]$nativeError }
}

function Save-ClinicHisCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidatePattern('^[^\\/:\s]+$')][string]$Target,
        [Parameter(Mandatory = $true)][ValidatePattern('^[^\\]+\\[^\\]+$')][string]$RemoteUser,
        [Parameter(Mandatory = $true)][string]$ExpectedSid,
        [string]$CurrentSid,
        [System.Security.SecureString]$Password,
        [scriptblock]$PasswordPrompt,
        [scriptblock]$CredentialWriter
    )

    Assert-ClinicCurrentAccountSid -ExpectedSid $ExpectedSid -CurrentSid $CurrentSid
    $securePassword = $Password
    $blob = [IntPtr]::Zero
    try {
        if ($null -eq $securePassword) {
            if ($null -ne $PasswordPrompt) {
                $securePassword = & $PasswordPrompt
            }
            else {
                $securePassword = Read-Host -Prompt ("Enter the HIS password for {0}" -f $Target) -AsSecureString
            }
        }
        if ($null -eq $securePassword -or $securePassword.Length -eq 0) {
            throw "The HIS password was empty or the prompt was cancelled. No credential was stored."
        }
        $blob = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($securePassword)
        $blobSize = $securePassword.Length * 2
        if ($null -ne $CredentialWriter) {
            $result = & $CredentialWriter $Target $RemoteUser $blob $blobSize 2 2
        }
        else {
            $result = Write-ClinicCredentialNative -Target $Target -RemoteUser $RemoteUser -Blob $blob -BlobSize $blobSize -CredentialType 2 -Persist 2
        }
        if ($null -eq $result -or -not $result.Success) {
            $errorCode = if ($null -ne $result) { [int]$result.ErrorCode } else { -1 }
            throw ("Credential Manager could not store the HIS credential (Windows error code {0})." -f $errorCode)
        }
        Write-Host ("[PASS] HIS credential was stored for target {0} under this application account." -f $Target) -ForegroundColor Green
        Write-Host "Stored does not confirm HIS access. Run verify_his_access.ps1 under this same account."
    }
    finally {
        if ($blob -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($blob)
        }
        if ($null -ne $securePassword) {
            $securePassword.Dispose()
        }
    }
}

function Resolve-ClinicAuthorizationSids {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$AccountSid,
        [object[]]$Memberships = @(),
        [bool]$MembershipsComplete = $true
    )

    $resolvedSids = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    [void]$resolvedSids.Add($AccountSid)
    [void]$resolvedSids.Add('S-1-1-0')       # Everyone
    [void]$resolvedSids.Add('S-1-5-11')      # Authenticated Users

    if ($MembershipsComplete) {
        $changed = $true
        while ($changed) {
            $changed = $false
            foreach ($edge in $Memberships) {
                if ($resolvedSids.Contains([string]$edge.MemberSid) -and $resolvedSids.Add([string]$edge.GroupSid)) {
                    $changed = $true
                }
            }
        }
    }

    return [PSCustomObject]@{
        Sids = [string[]]@($resolvedSids)
        Complete = [bool]$MembershipsComplete
    }
}

function Get-ClinicAuthorizationContext {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$AccountSid)

    $memberships = New-Object 'System.Collections.Generic.List[object]'
    $complete = $true
    try {
        $localGroups = @(Get-LocalGroup -ErrorAction Stop)
    }
    catch {
        return Resolve-ClinicAuthorizationSids -AccountSid $AccountSid -MembershipsComplete $false
    }

    foreach ($group in $localGroups) {
        try {
            $groupSid = $group.SID.Value
            $groupMembers = @(Get-LocalGroupMember -Group $group.Name -ErrorAction Stop)
            foreach ($member in $groupMembers) {
                $memberSid = $null
                if ($null -ne $member.SID) {
                    $memberSid = $member.SID.Value
                }
                elseif (-not [string]::IsNullOrWhiteSpace([string]$member.Name)) {
                    try {
                        $memberSid = ConvertTo-ClinicSecurityIdentifier -PrincipalUserId ([string]$member.Name)
                    }
                    catch {
                        $complete = $false
                    }
                }
                else {
                    $complete = $false
                }
                if ($null -ne $memberSid) {
                    $memberships.Add([PSCustomObject]@{ GroupSid = $groupSid; MemberSid = $memberSid })
                }
            }
        }
        catch {
            $complete = $false
        }
    }

    return Resolve-ClinicAuthorizationSids -AccountSid $AccountSid -Memberships $memberships.ToArray() -MembershipsComplete $complete
}

function Resolve-ClinicRuleSid {
    param([object]$Rule, [string]$Kind)

    $sidProperty = $Rule.PSObject.Properties['Sid']
    if ($null -ne $sidProperty -and -not [string]::IsNullOrWhiteSpace([string]$sidProperty.Value)) {
        return ([System.Security.Principal.SecurityIdentifier][string]$sidProperty.Value).Value
    }
    $identity = if ($Kind -eq 'Share') { [string]$Rule.AccountName } else { $Rule.IdentityReference }
    if ($identity -is [System.Security.Principal.SecurityIdentifier]) {
        return $identity.Value
    }
    try {
        $account = New-Object System.Security.Principal.NTAccount([string]$identity)
        return $account.Translate([System.Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        throw ("Could not resolve an ACL principal to a SID: {0}" -f [string]$identity)
    }
}

function Get-ClinicReadOnlyAccessDecision {
    [CmdletBinding()]
    param(
        [object[]]$Rules = @(),
        [string[]]$ApplicableSids = @(),
        [bool]$PrincipalGraphComplete = $false,
        [ValidateSet('FileSystem', 'Share')][string]$Kind = 'FileSystem'
    )

    if (-not $PrincipalGraphComplete) {
        return [PSCustomObject]@{ Allowed = $false; Reason = 'Local account group membership could not be fully resolved.' }
    }
    $sidSet = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($sid in $ApplicableSids) { [void]$sidSet.Add($sid) }

    $allowRead = $false
    foreach ($rule in $Rules) {
        try {
            $ruleSid = Resolve-ClinicRuleSid -Rule $rule -Kind $Kind
        }
        catch {
            return [PSCustomObject]@{ Allowed = $false; Reason = $_.Exception.Message }
        }
        if (-not $sidSet.Contains($ruleSid)) { continue }

        $accessType = [string]$rule.AccessControlType
        if ($accessType -eq 'Deny') {
            return [PSCustomObject]@{ Allowed = $false; Reason = 'A matching principal has a Deny entry.' }
        }
        if ($accessType -ne 'Allow') {
            return [PSCustomObject]@{ Allowed = $false; Reason = 'A matching ACL entry has an unknown access type.' }
        }

        if ($Kind -eq 'Share') {
            $right = [string]$rule.AccessRight
            if ($right -match '^(?i:Full|Change)$' -or $right -eq '2' -or $right -eq '3') {
                return [PSCustomObject]@{ Allowed = $false; Reason = 'A matching SMB principal has Change or Full access.' }
            }
            if ($right -match '^(?i:Read)$' -or $right -eq '1') {
                $allowRead = $true
                continue
            }
            return [PSCustomObject]@{ Allowed = $false; Reason = 'A matching SMB entry does not prove read access.' }
        }

        $rights = [int]$rule.FileSystemRights
        $readData = [int][System.Security.AccessControl.FileSystemRights]::ReadData
        $readOnlyMask = $readData -bor `
            [int][System.Security.AccessControl.FileSystemRights]::ReadAttributes -bor `
            [int][System.Security.AccessControl.FileSystemRights]::ReadExtendedAttributes -bor `
            [int][System.Security.AccessControl.FileSystemRights]::ReadPermissions -bor `
            [int][System.Security.AccessControl.FileSystemRights]::Synchronize -bor `
            [int][System.Security.AccessControl.FileSystemRights]::ExecuteFile
        if (($rights -band (-bnot $readOnlyMask)) -ne 0) {
            return [PSCustomObject]@{ Allowed = $false; Reason = 'A matching NTFS Allow entry includes rights outside read and execute.' }
        }
        if (($rights -band $readData) -ne 0) {
            $allowRead = $true
        }
    }

    if (-not $allowRead) {
        return [PSCustomObject]@{ Allowed = $false; Reason = 'No matching principal has an explicit Allow-read entry.' }
    }
    return [PSCustomObject]@{ Allowed = $true; Reason = 'Matching principals have an explicit read grant and no write-capable Allow entry.' }
}

Export-ModuleMember -Function `
    Set-DotEnvValue, `
    ConvertTo-ClinicSecurityIdentifier, `
    New-ClinicTaskSettings, `
    Assert-ClinicTaskConfiguration, `
    Get-ClinicPythonRuntimeInfo, `
    Assert-ClinicPythonEnvironment, `
    Assert-ClinicPythonCanRunAsUser, `
    Get-ClinicLocalAccountSid, `
    Assert-ClinicCurrentAccountSid, `
    Get-ClinicCredentialTarget, `
    Save-ClinicHisCredential, `
    Test-ClinicCredentialEntry, `
    Resolve-ClinicAuthorizationSids, `
    Get-ClinicAuthorizationContext, `
    Get-ClinicReadOnlyAccessDecision

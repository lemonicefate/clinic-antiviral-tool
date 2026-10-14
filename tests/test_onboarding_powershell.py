from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Settings


ROOT = Path(__file__).resolve().parent.parent


def _powershell_exe() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell 5.1 is required for onboarding behavior tests")
    return executable


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(tmp_path: Path, commands: str) -> subprocess.CompletedProcess[str]:
    script_path = tmp_path / "onboarding-probe.ps1"
    script_path.write_text(
        "$ErrorActionPreference = 'Stop'\n" + commands,
        encoding="utf-8-sig",
    )
    return subprocess.run(
        [
            _powershell_exe(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _assert_powershell_passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_onboarding_powershell_sources_parse_in_windows_powershell_51(tmp_path: Path) -> None:
    sources = [*sorted((ROOT / "scripts").glob("*.ps1")), *sorted((ROOT / "scripts").glob("*.psm1"))]
    paths = ",\n".join(_ps_quote(path) for path in sources)
    result = _run_powershell(
        tmp_path,
        f"""
if ($PSVersionTable.PSVersion.Major -ne 5) {{ throw 'These scripts must parse in Windows PowerShell 5.1.' }}
$paths = @(
{paths}
)
foreach ($path in $paths) {{
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {{ throw ("PowerShell parse failed for {0}: {1}" -f $path, $errors[0].Message) }}
}}
""",
    )
    _assert_powershell_passed(result)


def test_first_onboarding_writes_independent_utf8_settings_read_by_application_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "new clinic settings"
    config_dir.mkdir()
    env_path = config_dir / ".env"
    his_path = r"\\HIS01\HIS share\資料"
    app_data_path = r"C:\clinic data\app-data"

    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'HIS_MIRROR_PATH' -Value {_ps_quote(his_path)}
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'APP_DATA_PATH' -Value {_ps_quote(app_data_path)}
$lines = [System.IO.File]::ReadAllLines({_ps_quote(env_path)})
if ($lines.Count -ne 2) {{ throw "Expected two independent settings; found $($lines.Count): $($lines -join '|')" }}
""",
    )
    _assert_powershell_passed(result)
    assert not env_path.read_bytes().startswith(b"\xef\xbb\xbf")

    for key in ("HIS_MIRROR_PATH", "APP_DATA_PATH", "UPLOADED_PATH", "PORT"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env(base_dir=config_dir)

    assert str(settings.his_mirror_path) == his_path
    assert str(settings.app_data_path) == app_data_path


def test_dotenv_updates_existing_keys_without_duplicates_and_preserves_other_lines(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    env_path = config_dir / ".env"
    env_path.write_text(
        "# keep this comment\n"
        "UNRELATED=value\n"
        "SMIS_TEMPLATE_PATH=custom-template.xlsx\n"
        "PORT=8000\n",
        encoding="utf-8",
    )

    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'HIS_MIRROR_PATH' -Value '\\\\HIS01\\Share with spaces'
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'APP_DATA_PATH' -Value 'C:\\clinic data\\app-data'
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'HIS_MIRROR_PATH' -Value '\\\\HIS02\\Updated share'
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'SMIS_TEMPLATE_PATH' -Value 'ignored.xlsx' -OnlyIfMissing
""",
    )
    _assert_powershell_passed(result)

    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    assert lines.count("HIS_MIRROR_PATH=\\\\HIS02\\Updated share") == 1
    assert lines.count("APP_DATA_PATH=C:\\clinic data\\app-data") == 1
    assert "# keep this comment" in lines
    assert "UNRELATED=value" in lines
    assert "SMIS_TEMPLATE_PATH=custom-template.xlsx" in lines
    assert "PORT=8000" in lines


@pytest.mark.parametrize("initial_contents", [None, "", "EXISTING=value\n", "A=one\nB=two\n"])
def test_dotenv_writer_handles_missing_empty_single_and_multiple_line_files(
    tmp_path: Path, initial_contents: str | None
) -> None:
    env_path = tmp_path / "case.env"
    if initial_contents is not None:
        env_path.write_text(initial_contents, encoding="utf-8")

    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'FIRST' -Value 'one'
Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'SECOND' -Value 'two'
""",
    )
    _assert_powershell_passed(result)

    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    assert lines.count("FIRST=one") == 1
    assert lines.count("SECOND=two") == 1


def test_dotenv_writer_refuses_to_guess_how_to_repair_joined_settings(tmp_path: Path) -> None:
    env_path = tmp_path / "damaged.env"
    damaged = "HIS_MIRROR_PATH=\\\\HIS01\\ROOTAPP_DATA_PATH=C:\\clinic-data"
    env_path.write_text(damaged + "\n", encoding="utf-8")

    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
try {{
    Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'HIS_MIRROR_PATH' -Value '\\\\HIS01\\ROOT'
    throw 'Expected damaged configuration to be rejected.'
}}
catch {{ if ($_.Exception.Message -notmatch 'joined settings') {{ throw }} }}
""",
    )
    _assert_powershell_passed(result)
    assert env_path.read_text(encoding="utf-8") == damaged + "\n"


def test_dotenv_writer_leaves_invalid_utf8_configuration_untouched(tmp_path: Path) -> None:
    env_path = tmp_path / "invalid-utf8.env"
    damaged = b"HIS_MIRROR_PATH=\\\\HIS01\\ROOT\xff\n"
    env_path.write_bytes(damaged)

    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
try {{
    Set-DotEnvValue -Path {_ps_quote(env_path)} -Name 'HIS_MIRROR_PATH' -Value '\\\\HIS01\\ROOT'
    throw 'Expected invalid UTF-8 configuration to be rejected.'
}}
catch {{ if ($_.Exception.Message -notmatch 'valid UTF-8') {{ throw }} }}
""",
    )
    _assert_powershell_passed(result)
    assert env_path.read_bytes() == damaged


def test_start_task_validation_uses_real_cim_shape_and_scheduler_settings(tmp_path: Path) -> None:
    expected_sid = "S-1-5-21-100-200-300-1001"
    good_task = _scheduled_task_fixture(
        enabled=True,
        principal_sid=expected_sid,
        logon_type="Password",
        execute=r"C:\clinic-antiviral-tool\.venv\Scripts\python.exe",
        arguments=f"-m app.startup --expected-account-sid {expected_sid}",
        working_directory=r"C:\clinic-antiviral-tool",
        execution_time_limit="PT0S",
        boot_trigger=True,
    )
    fixtures = {
        "good": good_task,
        "disabled": _scheduled_task_fixture(enabled=False, principal_sid=expected_sid),
        "wrong_sid": _scheduled_task_fixture(principal_sid="S-1-5-21-999-888-777-1001"),
        "s4u": _scheduled_task_fixture(principal_sid=expected_sid, logon_type="S4U"),
        "bad_action": _scheduled_task_fixture(principal_sid=expected_sid, arguments="-m other.module"),
        "bad_directory": _scheduled_task_fixture(principal_sid=expected_sid, working_directory=r"C:\other"),
        "bad_python": _scheduled_task_fixture(principal_sid=expected_sid, execute=r"C:\Python312\python.exe"),
        "limited_runtime": _scheduled_task_fixture(
            principal_sid=expected_sid, execution_time_limit="PT72H"
        ),
        "no_startup": _scheduled_task_fixture(principal_sid=expected_sid, boot_trigger=False),
    }
    fixtures_literal = "\n".join(
        f"    '{name}' = {value}" for name, value in fixtures.items()
    )
    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
function New-CimFixture {{
    param([string]$ClassName, [System.Collections.IDictionary]$Values)
    $instance = [Microsoft.Management.Infrastructure.CimInstance]::new($ClassName)
    foreach ($name in $Values.Keys) {{
        $value = $Values[$name]
        if ($value -is [bool]) {{ $kind = [Microsoft.Management.Infrastructure.CimType]::Boolean }}
        elseif ($value -is [int]) {{ $kind = [Microsoft.Management.Infrastructure.CimType]::SInt32 }}
        elseif ($value -is [System.Array]) {{ $kind = [Microsoft.Management.Infrastructure.CimType]::InstanceArray; $value = [Microsoft.Management.Infrastructure.CimInstance[]]$value }}
        elseif ($value -is [Microsoft.Management.Infrastructure.CimInstance]) {{ $kind = [Microsoft.Management.Infrastructure.CimType]::Instance }}
        else {{ $kind = [Microsoft.Management.Infrastructure.CimType]::String }}
        $property = [Microsoft.Management.Infrastructure.CimProperty]::Create($name, $value, $kind, [Microsoft.Management.Infrastructure.CimFlags]::None)
        [void]$instance.CimInstanceProperties.Add($property)
    }}
    return $instance
}}
function New-TaskFixture {{
    param($Enabled, $PrincipalSid, $LogonType, $Execute, $Arguments, $WorkingDirectory, $ExecutionTimeLimit, $BootTrigger)
    $settings = New-CimFixture 'MSFT_TaskSettings' ([ordered]@{{
        Enabled = $Enabled; StartWhenAvailable = $true; RestartCount = 3;
        RestartInterval = 'PT1M'; ExecutionTimeLimit = $ExecutionTimeLimit
    }})
    $principal = New-CimFixture 'MSFT_TaskPrincipal' ([ordered]@{{ UserId = $PrincipalSid; LogonType = $LogonType }})
    $action = New-CimFixture 'MSFT_TaskExecAction' ([ordered]@{{
        Execute = $Execute; Arguments = $Arguments; WorkingDirectory = $WorkingDirectory
    }})
    $triggers = @()
    if ($BootTrigger) {{ $triggers = @(New-CimFixture 'MSFT_TaskBootTrigger' ([ordered]@{{ Enabled = $true }})) }}
    return New-CimFixture 'MSFT_ScheduledTask' ([ordered]@{{
        TaskName = 'ClinicAntiviralTool'; Settings = $settings; Principal = $principal;
        Actions = @($action); Triggers = $triggers
    }})
}}
$fixtures = @{{
{fixtures_literal}
}}
$expectedSid = '{expected_sid}'
$expectedRepo = 'C:\\clinic-antiviral-tool'
$expectedPython = 'C:\\clinic-antiviral-tool\\.venv\\Scripts\\python.exe'
$expectedArguments = '-m app.startup --expected-account-sid ' + $expectedSid
Assert-ClinicTaskConfiguration -Task $fixtures.good -ExpectedSid $expectedSid -ExpectedRepoPath $expectedRepo -ExpectedPythonPath $expectedPython -ExpectedArguments $expectedArguments
foreach ($name in @('disabled', 'wrong_sid', 's4u', 'bad_action', 'bad_directory', 'bad_python', 'limited_runtime', 'no_startup')) {{
    try {{
        Assert-ClinicTaskConfiguration -Task $fixtures[$name] -ExpectedSid $expectedSid -ExpectedRepoPath $expectedRepo -ExpectedPythonPath $expectedPython -ExpectedArguments $expectedArguments
        throw "Expected task fixture '$name' to be rejected."
    }}
    catch {{ if ($_.Exception.Message -notmatch 'Expected task fixture') {{ continue }}; throw }}
}}
$settings = New-ClinicTaskSettings
if ([System.Xml.XmlConvert]::ToTimeSpan([string]$settings.ExecutionTimeLimit) -ne [TimeSpan]::Zero) {{ throw "Expected no execution limit; got $($settings.ExecutionTimeLimit)." }}
if (-not $settings.StartWhenAvailable -or $settings.RestartCount -ne 3) {{ throw 'Startup and restart policy were not preserved.' }}
""",
    )
    _assert_powershell_passed(result)


def _scheduled_task_fixture(
    *,
    enabled: bool = True,
    principal_sid: str,
    logon_type: str = "Password",
    execute: str = r"C:\clinic-antiviral-tool\.venv\Scripts\python.exe",
    arguments: str | None = None,
    working_directory: str = r"C:\clinic-antiviral-tool",
    execution_time_limit: str = "PT0S",
    boot_trigger: bool = True,
) -> str:
    if arguments is None:
        arguments = f"-m app.startup --expected-account-sid {principal_sid}"
    enabled_value = "$true" if enabled else "$false"
    boot_value = "$true" if boot_trigger else "$false"
    return f"(New-TaskFixture {enabled_value} '{principal_sid}' '{logon_type}' '{execute}' '{arguments}' '{working_directory}' '{execution_time_limit}' {boot_value})"


def test_python_runtime_and_existing_venv_are_checked_before_onboarding(tmp_path: Path) -> None:
    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
$runtimeRoot = Join-Path {_ps_quote(tmp_path)} 'shared Python 312'
$venvRoot = Join-Path {_ps_quote(tmp_path)} 'repository venv'
$python = Join-Path $runtimeRoot 'python.exe'
$venvPython = Join-Path $venvRoot 'Scripts\\python.exe'
New-Item -ItemType Directory -Force -Path (Split-Path $python), (Split-Path $venvPython) | Out-Null
[System.IO.File]::WriteAllText($python, 'fixture')
[System.IO.File]::WriteAllText($venvPython, 'fixture')
[System.IO.File]::WriteAllText((Join-Path $venvRoot 'pyvenv.cfg'), "home = $runtimeRoot`r`n")
$probe = {{
    param([string]$Executable)
    if ([StringComparer]::OrdinalIgnoreCase.Equals($Executable, $venvPython)) {{
        return [PSCustomObject]@{{ Version = '3.12'; BasePrefix = $runtimeRoot }}
    }}
    return [PSCustomObject]@{{ Version = '3.12'; BasePrefix = $runtimeRoot }}
}}
$before = [System.IO.File]::ReadAllText((Join-Path $venvRoot 'pyvenv.cfg'))
$info = Assert-ClinicPythonEnvironment -PythonPath $python -VenvPath $venvRoot -RuntimeProbe $probe
if ($info.Version -ne '3.12') {{ throw 'The selected shared interpreter was not accepted.' }}
if ([System.IO.File]::ReadAllText((Join-Path $venvRoot 'pyvenv.cfg')) -ne $before) {{ throw 'A valid existing venv was modified.' }}

$wrongVersionProbe = {{ param([string]$Executable) return [PSCustomObject]@{{ Version = '3.11'; BasePrefix = $runtimeRoot }} }}
try {{ Assert-ClinicPythonEnvironment -PythonPath $python -VenvPath (Join-Path {_ps_quote(tmp_path)} 'new venv') -RuntimeProbe $wrongVersionProbe; throw 'Expected wrong Python version rejection.' }}
catch {{ if ($_.Exception.Message -notmatch '3.12') {{ throw }} }}

$failedProbe = {{ param([string]$Executable) throw 'synthetic incomplete Python runtime' }}
try {{ Get-ClinicPythonRuntimeInfo -PythonPath $python -RuntimeProbe $failedProbe; throw 'Expected an unusable Python runtime to be rejected.' }}
catch {{ if ($_.Exception.Message -notmatch 'failed its version and base-path check') {{ throw }} }}

[System.IO.File]::WriteAllText((Join-Path $venvRoot 'pyvenv.cfg'), "home = C:\\OtherPython`r`n")
try {{ Assert-ClinicPythonEnvironment -PythonPath $python -VenvPath $venvRoot -RuntimeProbe $probe; throw 'Expected wrong venv base rejection.' }}
catch {{ if ($_.Exception.Message -notmatch 'base') {{ throw }} }}

$missingProbeCalled = $false
$missingProbe = {{ $script:missingProbeCalled = $true; throw 'Probe should not run for a missing interpreter.' }}
try {{ Assert-ClinicPythonEnvironment -PythonPath (Join-Path {_ps_quote(tmp_path)} 'missing.exe') -VenvPath (Join-Path {_ps_quote(tmp_path)} 'new venv') -RuntimeProbe $missingProbe; throw 'Expected missing interpreter rejection.' }}
catch {{ if ($_.Exception.Message -notmatch 'does not exist') {{ throw }} }}
if ($missingProbeCalled) {{ throw 'The missing interpreter was probed.' }}
""",
    )
    _assert_powershell_passed(result)


def test_onboarding_requires_elevation_and_rejects_missing_python_before_mutations(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "fresh application checkout"
    repo.mkdir()
    missing_python = tmp_path / "shared Python" / "python.exe"
    result = subprocess.run(
        [
            _powershell_exe(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "onboard_app_host.ps1"),
            "-HisPath",
            r"\\HIS01\HISROOT",
            "-PythonPath",
            str(missing_python),
            "-RepoPath",
            str(repo),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode != 0
    assert (
        "Run onboard_app_host.ps1 from an elevated PowerShell window." in result.stderr
        or "interpreter does not exist" in result.stderr
    )
    assert not (repo / ".env").exists()
    assert not (repo / ".venv").exists()


def test_python_is_launched_in_the_application_account_context(tmp_path: Path) -> None:
    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
$python = Join-Path {_ps_quote(tmp_path)} 'shared runtime.exe'
[System.IO.File]::WriteAllText($python, 'fixture')
$password = New-Object System.Security.SecureString
foreach ($character in 'synthetic-only'.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
$credential = New-Object System.Management.Automation.PSCredential('APP01\\svc_clinic_tool', $password)
$captured = $null
$runner = {{ param($Executable, $Credential, $Arguments) $script:captured = @($Executable, $Credential.UserName, $Arguments); return [PSCustomObject]@{{ ExitCode = 0 }} }}
Assert-ClinicPythonCanRunAsUser -PythonPath $python -Credential $credential -ProcessRunner $runner
if ($captured[0] -ne $python -or $captured[1] -ne 'APP01\\svc_clinic_tool') {{ throw 'The selected runtime was not tested under the application account.' }}
if ($captured[2] -notmatch 'sys\\.version_info') {{ throw 'The account-context probe did not check Python startup.' }}
$failedRunner = {{ param($Executable, $Credential, $Arguments) return [PSCustomObject]@{{ ExitCode = 5 }} }}
try {{ Assert-ClinicPythonCanRunAsUser -PythonPath $python -Credential $credential -ProcessRunner $failedRunner; throw 'Expected failed account-context execution to stop onboarding.' }}
catch {{ if ($_.Exception.Message -notmatch 'application account') {{ throw }} }}
""",
    )
    _assert_powershell_passed(result)


def test_his_credential_uses_expected_sid_secure_prompt_and_native_write_boundary(
    tmp_path: Path,
) -> None:
    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
$expectedSid = 'S-1-5-21-100-200-300-1001'
$wrongSid = 'S-1-5-21-999-888-777-1001'
$script:promptCount = 0
$script:writeCount = 0
$script:readTarget = $null
$script:readType = $null
$script:captured = $null
$script:lastPromptPassword = $null
$prompt = {{
    $script:promptCount++
    $secure = New-Object System.Security.SecureString
    foreach ($character in 'test-his-secret'.ToCharArray()) {{ $secure.AppendChar($character) }}
    $secure.MakeReadOnly()
    $script:lastPromptPassword = $secure
    return $secure
}}
$writer = {{
    param($Target, $RemoteUser, $Blob, $BlobSize, $CredentialType, $Persist)
    $script:writeCount++
    $script:captured = [PSCustomObject]@{{
        Target = $Target; RemoteUser = $RemoteUser; CredentialType = $CredentialType; Persist = $Persist;
        Password = [Runtime.InteropServices.Marshal]::PtrToStringUni($Blob, [int]($BlobSize / 2))
    }}
    return [PSCustomObject]@{{ Success = $true; ErrorCode = 0 }}
}}
try {{ Save-ClinicHisCredential -Target '192.0.2.10' -RemoteUser 'HIS01\\svc_clinic_his_ro' -ExpectedSid $expectedSid -CurrentSid $wrongSid -PasswordPrompt $prompt -CredentialWriter $writer; throw 'Wrong account was accepted.' }}
catch {{ if ($_.Exception.Message -notmatch 'SID') {{ throw }} }}
if ($script:promptCount -ne 0 -or $script:writeCount -ne 0) {{ throw 'Wrong identity reached the prompt or Credential Manager.' }}

$credentialReader = {{
    param($Target, $CredentialType)
    $script:readTarget = $Target
    $script:readType = $CredentialType
    return [PSCustomObject]@{{ Exists = $true; ErrorCode = 0 }}
}}
$presentEntry = Test-ClinicCredentialEntry -Target '192.0.2.10' -CredentialReader $credentialReader
if (-not $presentEntry.Exists -or $script:readTarget -ne '192.0.2.10' -or $script:readType -ne 2) {{ throw 'Credential lookup did not query the matching domain-password target.' }}
$missingEntry = Test-ClinicCredentialEntry -Target '192.0.2.10' -CredentialReader {{ param($Target, $CredentialType) return [PSCustomObject]@{{ Exists = $false; ErrorCode = 1168 }} }}
if ($missingEntry.Exists -or $missingEntry.ErrorCode -ne 1168) {{ throw 'A missing credential entry was not reported.' }}

$emptyPrompt = {{ $script:promptCount++; return (New-Object System.Security.SecureString) }}
$emptyOutput = @()
try {{ $emptyOutput = @(Save-ClinicHisCredential -Target '192.0.2.10' -RemoteUser 'HIS01\\svc_clinic_his_ro' -ExpectedSid $expectedSid -CurrentSid $expectedSid -PasswordPrompt $emptyPrompt -CredentialWriter $writer 6>&1); throw 'Empty password was accepted.' }}
catch {{ if ($_.Exception.Message -notmatch 'empty') {{ throw }} }}
if ($script:writeCount -ne 0) {{ throw 'An empty password reached Credential Manager.' }}
if (($emptyOutput -join '') -match 'PASS') {{ throw 'Empty input printed a success message.' }}

$cancelPrompt = {{ $script:promptCount++; return $null }}
$cancelOutput = @()
try {{ $cancelOutput = @(Save-ClinicHisCredential -Target '192.0.2.10' -RemoteUser 'HIS01\\svc_clinic_his_ro' -ExpectedSid $expectedSid -CurrentSid $expectedSid -PasswordPrompt $cancelPrompt -CredentialWriter $writer 6>&1); throw 'Cancelled prompt was accepted.' }}
catch {{ if ($_.Exception.Message -notmatch 'cancelled') {{ throw }} }}
if (($cancelOutput -join '') -match 'PASS') {{ throw 'Cancelled input printed a success message.' }}

Save-ClinicHisCredential -Target '192.0.2.10' -RemoteUser 'HIS01\\svc_clinic_his_ro' -ExpectedSid $expectedSid -CurrentSid $expectedSid -PasswordPrompt $prompt -CredentialWriter $writer
if ($script:captured.Target -ne '192.0.2.10' -or $script:captured.RemoteUser -ne 'HIS01\\svc_clinic_his_ro') {{ throw 'Credential target or remote user was altered.' }}
if ($script:captured.CredentialType -ne 2 -or $script:captured.Persist -ne 2) {{ throw 'Wrong Credential Manager type or persistence.' }}
if ($script:captured.Password -ne 'test-his-secret') {{ throw 'Secure prompt value did not reach the native boundary.' }}
if ($script:writeCount -ne 1) {{ throw 'Successful storage should write once.' }}
$script:captured.Password = $null
$disposed = $false
try {{
    $testPointer = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($script:lastPromptPassword)
    [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($testPointer)
}} catch [System.ObjectDisposedException] {{ $disposed = $true }}
if (-not $disposed) {{ throw 'Secure prompt memory was not cleared after the native write.' }}

$failureWriter = {{ param($Target, $RemoteUser, $Blob, $BlobSize, $CredentialType, $Persist) return [PSCustomObject]@{{ Success = $false; ErrorCode = 5 }} }}
$failureOutput = @()
try {{ $failureOutput = @(Save-ClinicHisCredential -Target '192.0.2.10' -RemoteUser 'HIS01\\svc_clinic_his_ro' -ExpectedSid $expectedSid -CurrentSid $expectedSid -PasswordPrompt $prompt -CredentialWriter $failureWriter 6>&1); throw 'Native write failure was accepted.' }}
catch {{ if ($_.Exception.Message -notmatch '5') {{ throw }} }}
if (($failureOutput -join '') -match 'PASS') {{ throw 'Native write failure printed a success message.' }}

if ((Get-ClinicCredentialTarget -HisPath '\\\\192.0.2.10\\HIS share') -ne '192.0.2.10') {{ throw 'UNC IP was not converted to the Credential Manager target.' }}
""",
    )
    _assert_powershell_passed(result)
    assert "test-his-secret" not in result.stdout
    assert "test-his-secret" not in result.stderr


def test_his_host_acl_decision_requires_proven_sid_read_grants_and_rejects_write(
    tmp_path: Path,
) -> None:
    result = _run_powershell(
        tmp_path,
        f"""
Import-Module {_ps_quote(ROOT / 'scripts' / 'ClinicAntiviral.Onboarding.psm1')} -Force
$accountSid = 'S-1-5-21-100-200-300-1001'
$groupSid = 'S-1-5-21-100-200-300-2001'
$nestedGroupSid = 'S-1-5-21-100-200-300-2002'
$context = Resolve-ClinicAuthorizationSids -AccountSid $accountSid -Memberships @(
    [PSCustomObject]@{{ GroupSid = $groupSid; MemberSid = $accountSid }},
    [PSCustomObject]@{{ GroupSid = $nestedGroupSid; MemberSid = $groupSid }}
) -MembershipsComplete $true
if (-not $context.Complete -or $context.Sids -notcontains $nestedGroupSid) {{ throw 'Nested group SIDs were not resolved.' }}

$denyOnly = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = $accountSid; AccessControlType = 'Deny'; FileSystemRights = [int][Security.AccessControl.FileSystemRights]::ReadData }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind FileSystem
if ($denyOnly.Allowed) {{ throw 'A Deny-only ACL was reported as read access.' }}

$noRead = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = $accountSid; AccessControlType = 'Allow'; FileSystemRights = [int][Security.AccessControl.FileSystemRights]::WriteData }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind FileSystem
if ($noRead.Allowed) {{ throw 'Write access without a read grant was reported as read-only.' }}

$allowRead = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = $accountSid; AccessControlType = 'Allow'; FileSystemRights = [int][Security.AccessControl.FileSystemRights]::ReadAndExecute }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind FileSystem
if (-not $allowRead.Allowed) {{ throw "Explicit read-only ACL should pass: $($allowRead.Reason)" }}
$realAclRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    ([System.Security.Principal.SecurityIdentifier]$accountSid),
    [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    [Security.AccessControl.AccessControlType]::Allow
)
$realAclDecision = Get-ClinicReadOnlyAccessDecision -Rules @($realAclRule) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind FileSystem
if (-not $realAclDecision.Allowed) {{ throw "Windows ACL rule object should pass: $($realAclDecision.Reason)" }}

$nestedWrite = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = $nestedGroupSid; AccessControlType = 'Allow'; FileSystemRights = [int][Security.AccessControl.FileSystemRights]::Modify }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind FileSystem
if ($nestedWrite.Allowed) {{ throw 'Write permission through a nested group was not rejected.' }}

$unknown = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = $accountSid; AccessControlType = 'Allow'; FileSystemRights = [int][Security.AccessControl.FileSystemRights]::ReadData }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $false -Kind FileSystem
if ($unknown.Allowed) {{ throw 'Unknown group resolution was reported as safe.' }}

$shareRead = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = 'S-1-1-0'; AccessControlType = 'Allow'; AccessRight = 'Read' }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind Share
if (-not $shareRead.Allowed) {{ throw "Share read grant should pass: $($shareRead.Reason)" }}
$shareChange = Get-ClinicReadOnlyAccessDecision -Rules @(
    [PSCustomObject]@{{ Sid = $accountSid; AccessControlType = 'Allow'; AccessRight = 'Change' }}
) -ApplicableSids $context.Sids -PrincipalGraphComplete $context.Complete -Kind Share
if ($shareChange.Allowed) {{ throw 'SMB Change permission was reported as read-only.' }}
""",
    )
    _assert_powershell_passed(result)

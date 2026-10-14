from pathlib import Path

from app.logging_setup import configure_logging


def test_rotating_application_log_uses_runtime_path(tmp_path):
    log_path = tmp_path / "app-data" / "application.log"
    logger = configure_logging(log_path)
    logger.info("test operational identifier case_id=1")

    assert log_path.exists()
    assert "case_id=1" in log_path.read_text(encoding="utf-8")


def test_windows_operations_scripts_and_template_note_are_present():
    root = Path(__file__).resolve().parent.parent

    assert (root / "scripts" / "start.bat").exists()
    assert (root / "scripts" / "start_app_host.ps1").exists()
    assert (root / "scripts" / "stop.bat").exists()
    assert (root / "scripts" / "stop_app_host.ps1").exists()
    assert (root / "scripts" / "update.bat").exists()
    assert (root / "official-template" / "README.md").exists()


def test_host_onboarding_assets_are_present_and_his_verification_is_read_only():
    root = Path(__file__).resolve().parent.parent
    scripts = root / "scripts"

    verify_his = (scripts / "verify_his_host.ps1").read_text(encoding="utf-8")
    verify_access = (scripts / "verify_his_access.ps1").read_text(encoding="utf-8")
    store_credential = (scripts / "store_his_credential.ps1").read_text(encoding="utf-8")
    onboard = (scripts / "onboard_app_host.ps1").read_text(encoding="utf-8")
    onboarding_module = (scripts / "ClinicAntiviral.Onboarding.psm1").read_text(encoding="utf-8")
    startup = (root / "app" / "startup.py").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    for name in (
        "verify_his_host.ps1",
        "verify_his_access.ps1",
        "store_his_credential.ps1",
        "onboard_app_host.ps1",
    ):
        assert (scripts / name).exists()

    assert "New-LocalUser" not in verify_his
    assert "New-SmbShare" not in verify_his
    assert "Set-Acl" not in verify_his
    assert "Remove-SmbShare" not in verify_his
    assert "Set-LocalUser" not in verify_his
    assert "FileAccess]::Read" in verify_access
    assert "Test-ClinicCredentialEntry" in verify_access
    assert "/pass:" not in store_credential
    assert "PasswordNeverExpires" not in onboard
    assert "py.exe" not in onboard
    assert "PythonPath" in onboard
    assert "CredWriteW" in onboarding_module
    assert "cmdkey.exe" not in store_credential
    assert "SecureStringToGlobalAllocUnicode" in onboarding_module
    assert "New-ClinicTaskSettings" in onboard
    assert "ExecutionTimeLimit" in onboarding_module
    assert "LogonType" in onboarding_module
    assert "app.startup" in onboard
    assert 'table_path.open("rb")' in startup
    assert "Credential Manager" in readme
    assert "MANUAL ONLY" in readme
    assert "Task Scheduler" in readme
    assert "HIS_MIRROR_PATH" in readme
    assert "MUST NOT" in readme
    assert "## English" in readme
    assert "## 繁體中文" in readme

    elevation_check = onboard.index("\nAssert-Elevated\n")
    runtime_check = onboard.index("$pythonEnvironment = Assert-ClinicPythonEnvironment")
    account_lookup = onboard.index("$localUser = Get-LocalUser")
    repository_grant = onboard.index(
        'Grant-DirectoryAccess -Path $repo -Account $qualifiedAccount -Rights "(OI)(CI)RX"'
    )
    venv_account_check = onboard.index("Assert-ClinicPythonCanRunAsUser -PythonPath $venvPython")
    first_configuration_write = onboard.index('Set-DotEnvValue -Path $envPath')
    task_registration = onboard.index("Register-ScheduledTask @registrationParameters")
    assert elevation_check < runtime_check < account_lookup < repository_grant
    assert repository_grant < venv_account_check < first_configuration_write < task_registration

    start_launcher = (scripts / "start_app_host.ps1").read_text(encoding="utf-8")
    start_bat = (scripts / "start.bat").read_text(encoding="utf-8")
    assert "Start-ScheduledTask" in start_launcher
    assert "Credential Manager" in start_launcher
    assert "Assert-ClinicTaskConfiguration" in start_launcher
    assert "start_app_host.ps1" in start_bat
    assert "-m uvicorn app.main:app" not in start_bat
    stop_launcher = (scripts / "stop_app_host.ps1").read_text(encoding="utf-8")
    assert "ExecutablePath" in stop_launcher
    assert ".venv\\Scripts\\python.exe" in stop_launcher

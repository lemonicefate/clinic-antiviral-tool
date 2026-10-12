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
    assert (root / "scripts" / "update.bat").exists()
    assert (root / "official-template" / "README.md").exists()


def test_host_onboarding_assets_are_present_and_his_verification_is_read_only():
    root = Path(__file__).resolve().parent.parent
    scripts = root / "scripts"

    verify_his = (scripts / "verify_his_host.ps1").read_text(encoding="utf-8")
    verify_access = (scripts / "verify_his_access.ps1").read_text(encoding="utf-8")
    store_credential = (scripts / "store_his_credential.ps1").read_text(encoding="utf-8")
    onboard = (scripts / "onboard_app_host.ps1").read_text(encoding="utf-8")
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
    assert "/pass:" not in store_credential
    assert "PasswordNeverExpires" not in onboard
    assert "Credential Manager" in readme
    assert "MANUAL ONLY" in readme
    assert "Task Scheduler" in readme
    assert "HIS_MIRROR_PATH" in readme
    assert "MUST NOT" in readme

    start_launcher = (scripts / "start_app_host.ps1").read_text(encoding="utf-8")
    start_bat = (scripts / "start.bat").read_text(encoding="utf-8")
    assert "Start-ScheduledTask" in start_launcher
    assert "Credential Manager" in start_launcher
    assert "uvicorn" in start_launcher
    assert "start_app_host.ps1" in start_bat
    assert "-m uvicorn app.main:app" not in start_bat

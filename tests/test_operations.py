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
    assert (root / "scripts" / "stop.bat").exists()
    assert (root / "scripts" / "update.bat").exists()
    assert (root / "official-template" / "README.md").exists()

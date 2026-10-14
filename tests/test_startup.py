from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.startup import (
    StartupPreflightError,
    _current_windows_account_sid,
    _his_credential_target,
    launch_application,
)


ACCOUNT_SID = "S-1-5-21-100-200-300-1001"


@pytest.mark.parametrize(
    ("his_path", "target"),
    [
        (r"\\HIS01\HIS share", "HIS01"),
        (r"\\192.0.2.10\HIS share", "192.0.2.10"),
    ],
)
def test_his_credential_target_uses_unc_host(his_path: str, target: str) -> None:
    assert _his_credential_target(Path(his_path)) == target


def _settings_with_his_path(path: Path) -> Settings:
    return replace(Settings.for_testing(path.parent), his_mirror_path=path)


def _write_required_tables(path: Path) -> dict[Path, bytes]:
    data_dir = path / "DATA"
    data_dir.mkdir(parents=True)
    tables = {
        "CH012M1.DBF": path / "CH012M1.DBF",
        "CH011M1.DBF": data_dir / "CH011M1.DBF",
        "PD011M1.DBF": path / "PD011M1.DBF",
    }
    for table_path in tables.values():
        table_path.write_bytes(b"synthetic read-only startup fixture")
    return {table_path: table_path.read_bytes() for table_path in tables.values()}


def test_startup_preflight_reads_required_tables_then_runs_uvicorn_without_mutating_his(
    tmp_path: Path,
) -> None:
    his_path = tmp_path / "his mirror"
    original_tables = _write_required_tables(his_path)
    settings = _settings_with_his_path(his_path)
    calls: list[tuple[str, str, int]] = []

    launch_application(
        settings=settings,
        expected_account_sid=ACCOUNT_SID,
        current_account_sid=ACCOUNT_SID,
        his_credential_exists=lambda _path: True,
        server_runner=lambda app, host, port: calls.append((app, host, port)),
    )

    assert calls == [("app.main:app", settings.host, settings.port)]
    assert {path: path.read_bytes() for path in original_tables} == original_tables


@pytest.mark.parametrize(
    ("current_sid", "missing_table"),
    [("S-1-5-21-999-888-777-1001", None), (ACCOUNT_SID, "PD011M1.DBF")],
)
def test_startup_gate_prevents_uvicorn_when_identity_or_his_read_fails(
    tmp_path: Path, current_sid: str, missing_table: str | None
) -> None:
    his_path = tmp_path / "his mirror"
    _write_required_tables(his_path)
    if missing_table:
        (his_path / missing_table).unlink()
    calls: list[object] = []

    with pytest.raises(StartupPreflightError):
        launch_application(
            settings=_settings_with_his_path(his_path),
            expected_account_sid=ACCOUNT_SID,
            current_account_sid=current_sid,
            his_credential_exists=lambda _path: True,
            server_runner=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []


def test_startup_gate_rejects_missing_his_configuration_before_server_start(tmp_path: Path) -> None:
    settings = replace(Settings.for_testing(tmp_path), his_mirror_path=None)
    calls: list[object] = []

    with pytest.raises(StartupPreflightError, match="HIS path"):
        launch_application(
            settings=settings,
            expected_account_sid=ACCOUNT_SID,
            current_account_sid=ACCOUNT_SID,
            his_credential_exists=lambda _path: True,
            server_runner=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []


def test_startup_gate_stops_when_task_account_cannot_open_his_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    his_path = tmp_path / "his mirror"
    _write_required_tables(his_path)
    original_open = Path.open

    def fail_his_open(path: Path, *args, **kwargs):
        if path.name == "CH012M1.DBF":
            raise PermissionError("synthetic missing HIS credential")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_his_open)
    calls: list[object] = []

    with pytest.raises(StartupPreflightError, match="cannot be opened for read"):
        launch_application(
            settings=_settings_with_his_path(his_path),
            expected_account_sid=ACCOUNT_SID,
            current_account_sid=ACCOUNT_SID,
            his_credential_exists=lambda _path: True,
            server_runner=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []


def test_startup_gate_requires_a_credential_manager_entry_before_reading_his(
    tmp_path: Path,
) -> None:
    his_path = tmp_path / "his mirror"
    _write_required_tables(his_path)
    calls: list[object] = []

    with pytest.raises(StartupPreflightError, match="Credential Manager entry is missing"):
        launch_application(
            settings=_settings_with_his_path(his_path),
            expected_account_sid=ACCOUNT_SID,
            current_account_sid=ACCOUNT_SID,
            his_credential_exists=lambda _path: False,
            server_runner=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []


@pytest.mark.skipif(os.name != "nt", reason="Task identity lookup is Windows-only")
def test_startup_can_read_the_current_windows_sid() -> None:
    assert _current_windows_account_sid().startswith("S-1-")

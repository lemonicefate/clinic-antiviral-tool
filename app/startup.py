from __future__ import annotations

import argparse
import csv
import ctypes
import os
import re
import subprocess
import sys
from ctypes import wintypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.logging_setup import configure_logging


REQUIRED_HIS_TABLES = ("CH012M1.DBF", "CH011M1.DBF", "PD011M1.DBF")
_SID_PATTERN = re.compile(r"^S-1-\d+(?:-\d+)+$")
_UNC_HIS_PATH_PATTERN = re.compile(r"^\\\\(?P<host>[^\\]+)\\[^\\]+")
CRED_TYPE_DOMAIN_PASSWORD = 2
ERROR_NOT_FOUND = 1168


class StartupPreflightError(RuntimeError):
    """The scheduled task must stop before uvicorn when its prerequisites fail."""


def _current_windows_account_sid() -> str:
    if os.name != "nt":
        raise StartupPreflightError("The Windows task identity could not be checked on this platform.")
    try:
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        row = next(csv.reader(result.stdout.splitlines()))
        sid = row[-1].strip().lstrip("\ufeff")
    except (OSError, subprocess.CalledProcessError, StopIteration, csv.Error, IndexError) as exc:
        raise StartupPreflightError("The Windows task identity SID could not be read.") from exc
    if not _SID_PATTERN.fullmatch(sid):
        raise StartupPreflightError("The Windows task identity did not return a valid SID.")
    return sid


def _his_credential_target(his_path: Path) -> str:
    match = _UNC_HIS_PATH_PATTERN.match(str(his_path))
    if match is None:
        raise StartupPreflightError("The configured HIS path must be an explicit UNC path.")
    return match.group("host")


def _has_his_credential(his_path: Path) -> bool:
    """Check that this Windows account has a domain-password entry for the HIS host."""
    if os.name != "nt":
        raise StartupPreflightError("The HIS Credential Manager entry can only be checked on Windows.")
    target = _his_credential_target(his_path)

    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    cred_read.restype = wintypes.BOOL
    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None

    credential = ctypes.c_void_p()
    if not cred_read(target, CRED_TYPE_DOMAIN_PASSWORD, 0, ctypes.byref(credential)):
        error_code = ctypes.get_last_error()
        if error_code == ERROR_NOT_FOUND:
            return False
        raise StartupPreflightError(
            f"The HIS Credential Manager entry could not be checked (Windows error {error_code})."
        )
    if not credential.value:
        raise StartupPreflightError("Credential Manager returned an empty HIS credential entry.")
    try:
        return True
    finally:
        cred_free(credential)


def validate_startup(
    *,
    settings: Settings,
    expected_account_sid: str,
    current_account_sid: str | None = None,
    his_credential_exists: Callable[[Path], bool] | None = None,
) -> None:
    """Check the scheduled account, its HIS credential, and required HIS DBFs read-only."""
    if not _SID_PATTERN.fullmatch(expected_account_sid):
        raise StartupPreflightError("The scheduled task has no valid expected application account SID.")

    actual_sid = current_account_sid or _current_windows_account_sid()
    if actual_sid != expected_account_sid:
        raise StartupPreflightError("The scheduled task is running under the wrong Windows account SID.")

    his_path = settings.his_mirror_path
    if his_path is None:
        raise StartupPreflightError("HIS path is not configured. Complete onboarding before starting the application.")
    credential_check = his_credential_exists or _has_his_credential
    try:
        credential_is_present = credential_check(his_path)
    except StartupPreflightError:
        raise
    except Exception as exc:
        raise StartupPreflightError("The HIS Credential Manager entry could not be checked.") from exc
    if not credential_is_present:
        raise StartupPreflightError(
            "The HIS Credential Manager entry is missing for this task account. Complete credential setup before starting the application."
        )
    if not his_path.is_dir():
        raise StartupPreflightError("The configured HIS path is not available to the application task account.")

    for table_name in REQUIRED_HIS_TABLES:
        candidates = (his_path / table_name, his_path / "DATA" / table_name)
        table_path = next((path for path in candidates if path.is_file()), None)
        if table_path is None:
            raise StartupPreflightError(
                f"Required HIS table {table_name} is missing from the configured root or DATA directory."
            )
        try:
            with table_path.open("rb") as table_file:
                table_file.read(1)
        except OSError as exc:
            raise StartupPreflightError(
                f"Required HIS table {table_name} cannot be opened for read by the application task account."
            ) from exc


def launch_application(
    *,
    settings: Settings,
    expected_account_sid: str,
    current_account_sid: str | None = None,
    his_credential_exists: Callable[[Path], bool] | None = None,
    server_runner: Callable[..., Any] | None = None,
) -> None:
    """Run uvicorn only after task identity, credential, and HIS read checks pass."""
    validate_startup(
        settings=settings,
        expected_account_sid=expected_account_sid,
        current_account_sid=current_account_sid,
        his_credential_exists=his_credential_exists,
    )
    if server_runner is None:
        import uvicorn

        server_runner = uvicorn.run
    server_runner("app.main:app", host=settings.host, port=settings.port)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the clinic application after HIS read-only checks.")
    parser.add_argument("--expected-account-sid", required=True)
    arguments = parser.parse_args()

    settings = Settings.from_env()
    logger = configure_logging(settings.log_path)
    try:
        launch_application(
            settings=settings,
            expected_account_sid=arguments.expected_account_sid,
        )
    except StartupPreflightError as exc:
        logger.error("Application startup preflight blocked uvicorn: %s", exc)
        print(f"[FAIL] Application startup preflight failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

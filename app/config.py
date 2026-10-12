from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    his_mirror_path: Path | None
    app_data_path: Path
    database_path: Path
    uploaded_path: Path
    template_path: Path
    log_path: Path
    go_live_date: date | None
    host: str
    port: int

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> "Settings":
        base_dir = (base_dir or Path(__file__).resolve().parent.parent).resolve()
        load_dotenv(base_dir / ".env")
        app_data_path = _path_value("APP_DATA_PATH", Path("C:/clinic-data/app-data"), base_dir)
        uploaded_path = _path_value("UPLOADED_PATH", Path("C:/clinic-data/uploaded"), base_dir)
        database_path = _path_value("DATABASE_PATH", app_data_path / "clinic-antiviral.sqlite3", base_dir)
        log_path = _path_value("LOG_PATH", app_data_path / "application.log", base_dir)
        template_path = _path_value(
            "SMIS_TEMPLATE_PATH", base_dir / "official-template" / "smis_report.xlsx", base_dir
        )
        mirror_value = os.getenv("HIS_MIRROR_PATH", "").strip()
        his_mirror_path = _resolve_path(mirror_value, base_dir) if mirror_value else None
        go_live_value = os.getenv("GO_LIVE_DATE", "").strip()
        return cls(
            base_dir=base_dir,
            his_mirror_path=his_mirror_path,
            app_data_path=app_data_path,
            database_path=database_path,
            uploaded_path=uploaded_path,
            template_path=template_path,
            log_path=log_path,
            go_live_date=date.fromisoformat(go_live_value) if go_live_value else None,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
        )

    @classmethod
    def for_testing(cls, temp_path: Path) -> "Settings":
        app_data_path = temp_path / "app-data"
        return cls(
            base_dir=Path(__file__).resolve().parent.parent,
            his_mirror_path=temp_path / "his-mirror",
            app_data_path=app_data_path,
            database_path=app_data_path / "clinic-antiviral.sqlite3",
            uploaded_path=temp_path / "uploaded",
            template_path=temp_path / "smis_report.xlsx",
            log_path=app_data_path / "application.log",
            go_live_date=None,
            host="127.0.0.1",
            port=8000,
        )


def _path_value(name: str, default: Path, base_dir: Path) -> Path:
    value = os.getenv(name, "").strip()
    return _resolve_path(value, base_dir) if value else default


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path).resolve()

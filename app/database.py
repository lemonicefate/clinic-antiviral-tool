from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from app.his import Prescription


MISSING_REASON = "missing_reason"
MISSING_LOT_QUANTITY = "missing_lot_quantity"
READY_TO_EXPORT = "ready_to_export"
UPLOADED = "uploaded"
CONFIRMED = "confirmed"
EXCLUDED = "excluded"


@dataclass(frozen=True)
class CaseRecord:
    id: int
    source_id: str
    medical_record_number: str
    patient_name: str
    patient_id: str
    birth_date: date | None
    sex: str
    report_date: date
    doctor_id: str
    medication_id: str
    medication_name: str
    official_material: str
    source_quantity: int
    actual_quantity: int | None
    reason_code: str | None
    reason_label: str | None
    state: str
    exclusion_reason: str | None
    source_fingerprint: tuple[object, ...]
    created_at: str
    updated_at: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    medical_record_number TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    birth_date TEXT,
    sex TEXT NOT NULL,
    report_date TEXT NOT NULL,
    doctor_id TEXT NOT NULL,
    medication_id TEXT NOT NULL,
    medication_name TEXT NOT NULL,
    official_material TEXT NOT NULL,
    source_quantity INTEGER NOT NULL,
    actual_quantity INTEGER,
    reason_code TEXT,
    reason_label TEXT,
    state TEXT NOT NULL,
    exclusion_reason TEXT,
    source_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    lot_number TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS change_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    operator TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    operator TEXT NOT NULL,
    created_at TEXT NOT NULL,
    uploaded INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT,
    preserved_path TEXT
);

CREATE TABLE IF NOT EXISTS export_batch_cases (
    batch_id INTEGER NOT NULL REFERENCES export_batches(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    PRIMARY KEY (batch_id, case_id)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def get_case(self, case_id: int) -> CaseRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return _case_from_row(row) if row else None

    def get_case_by_source_id(self, source_id: str) -> CaseRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE source_id = ?", (source_id,)).fetchone()
        return _case_from_row(row) if row else None

    def count_cases(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0])

    def ensure_case(self, prescription: Prescription) -> CaseRecord:
        existing = self.get_case_by_source_id(prescription.source_id)
        if existing:
            return existing
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cases (
                    source_id, medical_record_number, patient_name, patient_id, birth_date, sex,
                    report_date, doctor_id, medication_id, medication_name, official_material,
                    source_quantity, actual_quantity, reason_code, reason_label, state,
                    exclusion_reason, source_fingerprint, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?, ?)
                """,
                _case_values(prescription)
                + (MISSING_REASON, _fingerprint_json(prescription), now, now),
            )
            case_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        return self.get_case(case_id)  # type: ignore[return-value]

    def save_doctor_reason(
        self,
        prescription: Prescription,
        reason_code: str,
        reason_label: str,
        operator: str,
    ) -> CaseRecord:
        existing = self.get_case_by_source_id(prescription.source_id)
        now = _now()
        with self._connect() as connection:
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO cases (
                        source_id, medical_record_number, patient_name, patient_id, birth_date, sex,
                        report_date, doctor_id, medication_id, medication_name, official_material,
                        source_quantity, actual_quantity, reason_code, reason_label, state,
                        exclusion_reason, source_fingerprint, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    _case_values(prescription)
                    + (
                        reason_code,
                        reason_label,
                        MISSING_LOT_QUANTITY,
                        _fingerprint_json(prescription),
                        now,
                        now,
                    ),
                )
                case_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            else:
                case_id = existing.id
                old_reason = _reason_value(existing.reason_code, existing.reason_label)
                new_reason = _reason_value(reason_code, reason_label)
                state = _state_for(
                    reason_code=reason_code,
                    actual_quantity=existing.actual_quantity,
                    lot_total=0,
                    lot_count=0,
                    previous_state=existing.state,
                )
                connection.execute(
                    """
                    UPDATE cases
                    SET reason_code = ?, reason_label = ?, state = ?, exclusion_reason = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (reason_code, reason_label, state, now, case_id),
                )
                if old_reason != new_reason:
                    connection.execute(
                        """
                        INSERT INTO change_history
                            (case_id, field, old_value, new_value, operator, changed_at)
                        VALUES (?, 'medication_use_reason', ?, ?, ?, ?)
                        """,
                        (case_id, old_reason, new_reason, operator, now),
                    )
        return self.get_case(case_id)  # type: ignore[return-value]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _case_values(prescription: Prescription) -> tuple[object, ...]:
    return (
        prescription.source_id,
        prescription.medical_record_number,
        prescription.patient_name,
        prescription.patient_id,
        prescription.birth_date.isoformat() if prescription.birth_date else None,
        prescription.sex,
        prescription.report_date.isoformat(),
        prescription.doctor_id,
        prescription.medication_id,
        prescription.medication_name,
        prescription.official_material,
        prescription.source_quantity,
        prescription.source_quantity,
    )


def _case_from_row(row: sqlite3.Row) -> CaseRecord:
    return CaseRecord(
        id=int(row["id"]),
        source_id=row["source_id"],
        medical_record_number=row["medical_record_number"],
        patient_name=row["patient_name"],
        patient_id=row["patient_id"],
        birth_date=date.fromisoformat(row["birth_date"]) if row["birth_date"] else None,
        sex=row["sex"],
        report_date=date.fromisoformat(row["report_date"]),
        doctor_id=row["doctor_id"],
        medication_id=row["medication_id"],
        medication_name=row["medication_name"],
        official_material=row["official_material"],
        source_quantity=int(row["source_quantity"]),
        actual_quantity=int(row["actual_quantity"]) if row["actual_quantity"] is not None else None,
        reason_code=row["reason_code"],
        reason_label=row["reason_label"],
        state=row["state"],
        exclusion_reason=row["exclusion_reason"],
        source_fingerprint=tuple(json.loads(row["source_fingerprint"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _fingerprint_json(prescription: Prescription) -> str:
    values = [value.isoformat() if isinstance(value, date) else value for value in prescription.reporting_fingerprint]
    return json.dumps(values, ensure_ascii=False)


def _reason_value(code: str | None, label: str | None) -> str | None:
    if not code and not label:
        return None
    return f"{code or ''}: {label or ''}".strip()


def _state_for(
    *,
    reason_code: str | None,
    actual_quantity: int | None,
    lot_total: int,
    lot_count: int,
    previous_state: str | None = None,
) -> str:
    if previous_state == EXCLUDED:
        return EXCLUDED
    if not reason_code:
        return MISSING_REASON
    if actual_quantity is None or actual_quantity <= 0 or lot_count == 0 or lot_total != actual_quantity:
        return MISSING_LOT_QUANTITY
    return READY_TO_EXPORT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

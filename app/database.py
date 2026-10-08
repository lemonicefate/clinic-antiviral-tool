from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from app.cases import (
    CONFIRMED,
    EXCLUDED,
    MISSING_LOT_QUANTITY,
    MISSING_REASON,
    READY_TO_EXPORT,
    LotAllocation,
    MixedMedicationBatchError,
    CaseFieldError,
    derive_state,
    lots_display,
)
from app.his import Prescription


UPLOADED = "uploaded"


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
    lots: tuple[LotAllocation, ...] = ()


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
        return self._case_with_lots(row) if row else None

    def get_case_by_source_id(self, source_id: str) -> CaseRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE source_id = ?", (source_id,)).fetchone()
        return self._case_with_lots(row) if row else None

    def count_cases(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0])

    def list_cases(
        self,
        *,
        include_completed: bool = False,
        include_excluded: bool = False,
        report_date: date | None = None,
        state: str | None = None,
        doctor_id: str | None = None,
        medication_id: str | None = None,
    ) -> list[CaseRecord]:
        clauses: list[str] = []
        values: list[object] = []
        if not include_completed:
            clauses.append("state != ?")
            values.append(CONFIRMED)
        if not include_excluded:
            clauses.append("state != ?")
            values.append(EXCLUDED)
        if report_date:
            clauses.append("report_date = ?")
            values.append(report_date.isoformat())
        if state:
            clauses.append("state = ?")
            values.append(state)
        if doctor_id:
            clauses.append("doctor_id = ?")
            values.append(doctor_id)
        if medication_id:
            clauses.append("medication_id = ?")
            values.append(medication_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM cases {where} ORDER BY report_date DESC, id DESC", values
            ).fetchall()
        return [self._case_with_lots(row) for row in rows]

    def save_pharmacy_fields(
        self,
        case_id: int,
        *,
        reason_code: str | None,
        reason_label: str | None,
        actual_quantity: int | None,
        lots: tuple[LotAllocation, ...],
        operator: str,
    ) -> CaseRecord:
        existing = self.get_case(case_id)
        if existing is None:
            raise KeyError(case_id)
        now = _now()
        state = derive_state(
            reason_code=reason_code,
            actual_quantity=actual_quantity,
            lots=lots,
            previous_state=existing.state,
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE cases
                SET reason_code = ?, reason_label = ?, actual_quantity = ?, state = ?,
                    exclusion_reason = CASE WHEN state = ? THEN exclusion_reason ELSE NULL END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    reason_code,
                    reason_label,
                    actual_quantity,
                    state,
                    EXCLUDED,
                    now,
                    case_id,
                ),
            )
            connection.execute("DELETE FROM case_lots WHERE case_id = ?", (case_id,))
            connection.executemany(
                "INSERT INTO case_lots (case_id, lot_number, quantity, position) VALUES (?, ?, ?, ?)",
                [(case_id, lot.lot_number, lot.quantity, index) for index, lot in enumerate(lots)],
            )
            _record_change_if_needed(
                connection,
                case_id=case_id,
                field="medication_use_reason",
                old_value=_reason_value(existing.reason_code, existing.reason_label),
                new_value=_reason_value(reason_code, reason_label),
                operator=operator,
                changed_at=now,
            )
            _record_change_if_needed(
                connection,
                case_id=case_id,
                field="actual_quantity",
                old_value=str(existing.actual_quantity) if existing.actual_quantity is not None else None,
                new_value=str(actual_quantity) if actual_quantity is not None else None,
                operator=operator,
                changed_at=now,
            )
            _record_change_if_needed(
                connection,
                case_id=case_id,
                field="lot_number",
                old_value=lots_display(existing.lots) or None,
                new_value=lots_display(lots) or None,
                operator=operator,
                changed_at=now,
            )
        return self.get_case(case_id)  # type: ignore[return-value]

    def batch_assign_lot(
        self,
        case_ids: Iterable[int],
        *,
        lot_number: str,
        operator: str,
    ) -> list[CaseRecord]:
        ids = tuple(dict.fromkeys(int(case_id) for case_id in case_ids))
        cases = [case for case_id in ids if (case := self.get_case(case_id)) is not None]
        if not cases or len(cases) != len(ids):
            raise KeyError("case")
        if not lot_number.strip():
            raise CaseFieldError("Enter a lot number before batch assignment.")
        if len({case.medication_id for case in cases}) != 1:
            raise MixedMedicationBatchError(
                "Separate medications before applying one lot to several cases."
            )
        if any(case.actual_quantity is None or case.actual_quantity <= 0 for case in cases):
            raise CaseFieldError("Enter an actual quantity before batch lot assignment.")

        now = _now()
        with self._connect() as connection:
            for case in cases:
                lots = (LotAllocation(lot_number.strip(), case.actual_quantity),)
                state = derive_state(
                    reason_code=case.reason_code,
                    actual_quantity=case.actual_quantity,
                    lots=lots,
                    previous_state=case.state,
                )
                connection.execute(
                    "UPDATE cases SET state = ?, updated_at = ? WHERE id = ?",
                    (state, now, case.id),
                )
                connection.execute("DELETE FROM case_lots WHERE case_id = ?", (case.id,))
                connection.execute(
                    "INSERT INTO case_lots (case_id, lot_number, quantity, position) VALUES (?, ?, ?, 0)",
                    (case.id, lot_number.strip(), case.actual_quantity),
                )
                _record_change_if_needed(
                    connection,
                    case_id=case.id,
                    field="lot_number",
                    old_value=lots_display(case.lots) or None,
                    new_value=lots_display(lots),
                    operator=operator,
                    changed_at=now,
                )
        return [self.get_case(case.id) for case in cases]  # type: ignore[misc]

    def exclude_case(self, case_id: int, exclusion_reason: str) -> CaseRecord:
        existing = self.get_case(case_id)
        if existing is None:
            raise KeyError(case_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE cases SET state = ?, exclusion_reason = ?, updated_at = ? WHERE id = ?",
                (EXCLUDED, exclusion_reason, _now(), case_id),
            )
        return self.get_case(case_id)  # type: ignore[return-value]

    def reinclude_case(self, case_id: int) -> CaseRecord:
        existing = self.get_case(case_id)
        if existing is None:
            raise KeyError(case_id)
        state = derive_state(
            reason_code=existing.reason_code,
            actual_quantity=existing.actual_quantity,
            lots=existing.lots,
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE cases SET state = ?, exclusion_reason = NULL, updated_at = ? WHERE id = ?",
                (state, _now(), case_id),
            )
        return self.get_case(case_id)  # type: ignore[return-value]

    def list_history(self, case_id: int) -> list[dict[str, str | None]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT changed_at, operator, field, old_value, new_value
                FROM change_history WHERE case_id = ? ORDER BY id DESC
                """,
                (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _case_with_lots(self, row: sqlite3.Row) -> CaseRecord:
        case = _case_from_row(row)
        with self._connect() as connection:
            lots = connection.execute(
                "SELECT lot_number, quantity FROM case_lots WHERE case_id = ? ORDER BY position",
                (case.id,),
            ).fetchall()
        return CaseRecord(
            **{**case.__dict__, "lots": tuple(LotAllocation(row["lot_number"], int(row["quantity"])) for row in lots)}
        )

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
                state = derive_state(
                    reason_code=reason_code,
                    actual_quantity=existing.actual_quantity,
                    lots=existing.lots,
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


def _record_change_if_needed(
    connection: sqlite3.Connection,
    *,
    case_id: int,
    field: str,
    old_value: str | None,
    new_value: str | None,
    operator: str,
    changed_at: str,
) -> None:
    if old_value == new_value:
        return
    connection.execute(
        """
        INSERT INTO change_history (case_id, field, old_value, new_value, operator, changed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (case_id, field, old_value, new_value, operator, changed_at),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

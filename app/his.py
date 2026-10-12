from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import threading
from typing import Callable, Iterable, Iterator, Protocol

from dbfread import DBF

from app.medications import PUBLIC_ANTIVIRALS, MedicationMapping, find_medication_mapping


class HisReadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DateRangeError(HisReadError):
    def __init__(self):
        super().__init__("HIS_RANGE_001", "The HIS scan range must be 31 days or less.")


class HisIndexBuilding(HisReadError):
    def __init__(self):
        super().__init__("HIS_INDEX_001", "Today's HIS index is still being built.")


class HisIndexStale(HisReadError):
    def __init__(self):
        super().__init__("HIS_INDEX_002", "Today's HIS index needs to be updated.")


@dataclass(frozen=True)
class _DbfCursor:
    signature: tuple[int, int] | None
    num_records: int
    record_length: int
    header_length: int
    tail_digest: str | None


@dataclass(frozen=True)
class Prescription:
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
    unit: str
    source_quantity: int
    treat: str
    report_time: time | None = None

    @property
    def reporting_fingerprint(self) -> tuple[object, ...]:
        return (
            self.medical_record_number,
            self.patient_name,
            self.patient_id,
            self.birth_date,
            self.sex,
            self.report_date,
            self.doctor_id,
            self.medication_id,
            self.official_material,
            self.source_quantity,
            self.treat,
        )


class HisReader(Protocol):
    def most_recent(self, doctor_id: str) -> Prescription | None: ...

    def recent_candidates(
        self,
        doctor_id: str,
        *,
        start_time: time | None = None,
    ) -> list[Prescription]: ...

    def find_by_mrn(self, medical_record_number: str, doctor_id: str | None = None) -> list[Prescription]: ...

    def scan(self, start_date: date, end_date: date) -> list[Prescription]: ...

    def get(self, source_id: str) -> Prescription | None: ...


class InMemoryHisReader:
    """Small test and development seam with the same behavior as the DBF reader."""

    def __init__(
        self,
        prescriptions: Iterable[Prescription],
        today_provider: Callable[[], date] | None = None,
    ):
        self._prescriptions = tuple(prescriptions)
        self._today_provider = today_provider or date.today

    def most_recent(self, doctor_id: str) -> Prescription | None:
        matches = self.recent_candidates(doctor_id)
        return _sort_prescriptions(matches)[0] if matches else None

    def recent_candidates(
        self,
        doctor_id: str,
        *,
        start_time: time | None = None,
    ) -> list[Prescription]:
        today = self._today_provider()
        matches = [
            item
            for item in self._prescriptions
            if item.doctor_id == doctor_id
            and item.report_date == today
            and (start_time is None or (item.report_time is not None and item.report_time >= start_time))
        ]
        return _sort_prescriptions(matches)

    def find_by_mrn(self, medical_record_number: str, doctor_id: str | None = None) -> list[Prescription]:
        matches = [
            item
            for item in self._prescriptions
            if item.medical_record_number == medical_record_number
            and (doctor_id is None or item.doctor_id == doctor_id)
        ]
        return _sort_prescriptions(matches)

    def scan(self, start_date: date, end_date: date) -> list[Prescription]:
        _validate_date_range(start_date, end_date)
        return _sort_prescriptions(
            item for item in self._prescriptions if start_date <= item.report_date <= end_date
        )

    def get(self, source_id: str) -> Prescription | None:
        return next((item for item in self._prescriptions if item.source_id == source_id), None)


class DbfHisReader:
    """Read the small set of known HIS DBF tables without ever opening them for writing."""

    def __init__(
        self,
        mirror_path: Path | None,
        mappings: Iterable[MedicationMapping] = PUBLIC_ANTIVIRALS,
        today_provider: Callable[[], date] | None = None,
    ):
        self.mirror_path = mirror_path
        self.mappings = tuple(mappings)
        self._today_provider = today_provider or date.today
        self._table_paths: dict[str, Path | None] = {}
        self._table_paths_discovered = False
        self._table_cache: dict[str, tuple[tuple[int, int], list[dict[str, object]]]] = {}
        self._prescription_cache: list[Prescription] | None = None
        self._prescription_cache_signatures: dict[str, tuple[int, int]] = {}
        self._today_cache: dict[
            tuple[date, str],
            tuple[dict[str, tuple[int, int] | None], list[Prescription]],
        ] = {}
        self._index_lock = threading.RLock()
        self._index_status_lock = threading.Lock()
        self._today_index_date: date | None = None
        self._today_index_by_doctor: dict[str, list[Prescription]] = {}
        self._today_index_signatures: dict[str, tuple[int, int] | None] = {}
        self._today_index_cursors: dict[str, _DbfCursor | None] = {}
        self._today_index_state = "not_started"
        self._today_index_progress = 0
        self._today_index_message = "尚未建立今日索引"
        self._today_index_started_at: datetime | None = None
        self._today_index_completed_at: datetime | None = None
        self._today_index_first_completed_at: datetime | None = None
        self._today_index_error: str | None = None
        self._today_index_phase = "idle"
        self._today_index_processed = 0
        self._today_index_total = 0
        self._today_index_progress_mode = "determinate"
        self._today_index_updated_at: datetime | None = None
        self._today_index_thread: threading.Thread | None = None
        self._today_index_headers_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        self._today_index_headers_by_relkey: dict[str, list[dict[str, object]]] = {}
        self._today_index_items: list[tuple[dict[str, object], MedicationMapping, str]] = []
        self._today_index_patients_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        self._today_index_inventory_by_item: dict[str, dict[str, object]] = {}
        self._today_index_pending_items: list[tuple[dict[str, object], MedicationMapping, str]] = []

    def most_recent(self, doctor_id: str) -> Prescription | None:
        matches = self.recent_candidates(doctor_id)
        return _sort_prescriptions(matches)[0] if matches else None

    def recent_candidates(
        self,
        doctor_id: str,
        *,
        start_time: time | None = None,
    ) -> list[Prescription]:
        doctor_id = doctor_id.strip()
        if not doctor_id:
            return []
        self._ensure_today_index()
        matches = list(self._today_index_by_doctor.get(doctor_id, []))
        if start_time is not None:
            matches = [
                item
                for item in matches
                if item.report_time is not None and item.report_time >= start_time
            ]
        return _sort_prescriptions(matches)

    def index_status(self) -> dict[str, object]:
        with self._index_status_lock:
            return {
                "state": self._today_index_state,
                "progress": self._today_index_progress,
                "message": self._today_index_message,
                "started_at": self._today_index_started_at.isoformat(timespec="seconds")
                if self._today_index_started_at
                else None,
                "completed_at": self._today_index_completed_at.isoformat(timespec="seconds")
                if self._today_index_completed_at
                else None,
                "first_completed_at": self._today_index_first_completed_at.isoformat(timespec="seconds")
                if self._today_index_first_completed_at
                else None,
                "phase": self._today_index_phase,
                "processed": self._today_index_processed,
                "total": self._today_index_total,
                "progress_mode": self._today_index_progress_mode,
                "updated_at": self._today_index_updated_at.isoformat(timespec="seconds")
                if self._today_index_updated_at
                else None,
                "error": self._today_index_error,
            }

    def start_today_index_build(self, *, force: bool = False) -> bool:
        with self._index_status_lock:
            if self._today_index_thread and self._today_index_thread.is_alive():
                return False
            today = self._today_provider()
            if (
                not force
                and self._today_index_date == today
                and self._today_index_state == "ready"
            ):
                return False
            # Publish the building state before starting the thread so a
            # request arriving in the tiny scheduling window cannot start a
            # second synchronous full scan.
            self._today_index_date = today
            self._today_index_state = "building"
            self._today_index_progress = 0
            self._today_index_message = "正在建立今日索引"
            now = datetime.now()
            self._today_index_started_at = now
            self._today_index_completed_at = None
            self._today_index_error = None
            self._today_index_phase = "prepare"
            self._today_index_processed = 0
            self._today_index_total = 0
            self._today_index_progress_mode = "indeterminate"
            self._today_index_updated_at = now
            self._today_index_thread = threading.Thread(
                target=self._build_today_index_worker,
                kwargs={"force": force},
                name="clinic-today-index",
                daemon=True,
            )
            self._today_index_thread.start()
            return True

    def prepare_today_index(self, *, force: bool = False) -> None:
        """Build the shared today's index using read-only DBF streams."""
        self._build_today_index_worker(force=force, raise_errors=True)

    def find_by_mrn(self, medical_record_number: str, doctor_id: str | None = None) -> list[Prescription]:
        matches = [
            item
            for item in self._all_prescriptions()
            if item.medical_record_number == medical_record_number
            and (doctor_id is None or item.doctor_id == doctor_id)
        ]
        return _sort_prescriptions(matches)

    def scan(self, start_date: date, end_date: date) -> list[Prescription]:
        _validate_date_range(start_date, end_date)
        return _sort_prescriptions(
            item
            for item in self._all_prescriptions()
            if start_date <= item.report_date <= end_date
        )

    def get(self, source_id: str) -> Prescription | None:
        # Export/save re-checks deliberately bypass every in-memory snapshot.
        # Only the selected order is reconstructed from the read-only DBFs.
        return self._read_selected_order(source_id.strip()) if source_id.strip() else None

    def _all_prescriptions(self, *, force_refresh: bool = False) -> list[Prescription]:
        if self.mirror_path is None:
            raise HisReadError("HIS_READ_001", "HIS mirror is not configured.")
        if not self.mirror_path.exists() or not self.mirror_path.is_dir():
            raise HisReadError("HIS_READ_001", "Configured HIS mirror cannot be read.")
        if not force_refresh and self._prescription_cache is not None and self._cache_is_current():
            return self._prescription_cache
        if force_refresh:
            self._table_cache.clear()

        self._discover_table_paths()
        items = self._read_table("CH012M1")
        headers = self._read_table("CH011M1")
        patients = self._read_table("PD011M1")
        inventory_by_item: dict[str, dict[str, object]] = {}
        inventory_loaded = False
        headers_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        headers_by_relkey: dict[str, list[dict[str, object]]] = {}
        for row in headers:
            key = _join_key(row)
            if key != ("", ""):
                headers_by_key.setdefault(key, []).append(row)
            if key[0]:
                headers_by_relkey.setdefault(key[0], []).append(row)
        patients_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in patients:
            key = _patient_key(row)
            if key != ("", ""):
                patients_by_key.setdefault(key, []).append(row)

        prescriptions: list[Prescription] = []
        for item in items:
            inventory_row: dict[str, object] = {}
            mapping = find_medication_mapping(
                med1=_value(item, "MED1", "MEDICATION", "DRUG"),
                itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
                labnum="",
                mappings=self.mappings,
            )
            if mapping is None and not inventory_loaded:
                inventory = self._read_table("H_INV", required=False)
                inventory_by_item = {
                    _text(_value(row, "ITEMN", "ITEM_NO", "ITEMNO")): row for row in inventory
                }
                inventory_loaded = True
            if mapping is None:
                inventory_row = inventory_by_item.get(
                    _text(_value(item, "ITEMN", "ITEM_NO", "ITEMNO")), {}
                )
                mapping = find_medication_mapping(
                    med1=_value(item, "MED1", "MEDICATION", "DRUG"),
                    itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
                    labnum=_value(inventory_row, "LABNUM", "LAB_NO", "NHI_CODE"),
                    mappings=self.mappings,
                )
            if mapping is None:
                continue

            header = _choose_header(headers_by_key, headers_by_relkey, item)
            if not header:
                continue
            treat = _text(_value(item, "TREAT")) or _text(_value(header, "TREAT"))
            if treat and treat not in {"Y", "C", "N"}:
                continue
            patient = _choose_patient(patients_by_key, header)
            try:
                prescription = _normalise_prescription(item, header, mapping, treat, patient=patient)
                if not (
                    prescription.patient_name
                    and prescription.medical_record_number
                    and prescription.patient_id
                ):
                    continue
                prescriptions.append(prescription)
            except (ValueError, TypeError, InvalidOperation):
                continue
        self._prescription_cache = prescriptions
        self._prescription_cache_signatures = {
            table_name: signature
            for table_name, (signature, _) in self._table_cache.items()
        }
        return prescriptions

    def _ensure_today_index(self) -> None:
        today = self._today_provider()
        with self._index_status_lock:
            state = self._today_index_state
            index_date = self._today_index_date
        if index_date != today:
            with self._index_lock:
                self._reset_today_index_state(today)
            self.prepare_today_index(force=True)
            return
        if state == "building":
            raise HisIndexBuilding()
        if state == "error":
            raise HisReadError("HIS_READ_001", "Today's HIS index cannot be built.")
        if state != "ready":
            self.prepare_today_index(force=True)
            return
        try:
            self._refresh_today_index_if_needed()
        except HisIndexStale:
            with self._index_status_lock:
                self._today_index_state = "stale"
                self._today_index_message = "今日索引需要更新"
            raise

    def _build_today_index_worker(self, *, force: bool = False, raise_errors: bool = False) -> None:
        try:
            with self._index_lock:
                today = self._today_provider()
                with self._index_status_lock:
                    self._today_index_completed_at = None
                self._set_index_status(
                    "building",
                    0,
                    "正在準備建立今日索引",
                    started_at=datetime.now(),
                    completed_at=None,
                    error=None,
                    phase="prepare",
                    processed=0,
                    total=0,
                    progress_mode="indeterminate",
                )
                state = self._build_today_index(today)
                self._today_index_date = today
                self._today_index_by_doctor = _group_by_doctor(state["prescriptions"])
                self._today_index_signatures = {
                    table_name: cursor.signature if cursor else None
                    for table_name, cursor in state["cursors"].items()
                }
                self._today_index_cursors = state["cursors"]
                self._today_index_headers_by_key = state["headers_by_key"]
                self._today_index_headers_by_relkey = state["headers_by_relkey"]
                self._today_index_items = state["items"]
                self._today_index_pending_items = state["pending_items"]
                self._today_index_patients_by_key = state["patients_by_key"]
                self._today_index_inventory_by_item = state["inventory_by_item"]
                self._today_cache.clear()
                self._prescription_cache = None
                self._prescription_cache_signatures = {}
                self._set_index_status(
                    "ready",
                    100,
                    "今日索引已完成",
                    completed_at=datetime.now(),
                    error=None,
                    phase="ready",
                    processed=0,
                    total=0,
                    progress_mode="determinate",
                )
                with self._index_status_lock:
                    if self._today_index_first_completed_at is None:
                        self._today_index_first_completed_at = self._today_index_completed_at
        except Exception as error:
            with self._index_status_lock:
                failed_progress = self._today_index_progress
                failed_processed = self._today_index_processed
                failed_total = self._today_index_total
                failed_mode = self._today_index_progress_mode
            self._set_index_status(
                "error",
                failed_progress,
                "今日索引建立失敗",
                completed_at=datetime.now(),
                error=str(error),
                phase="error",
                processed=failed_processed,
                total=failed_total,
                progress_mode=failed_mode,
            )
            if raise_errors:
                if isinstance(error, HisReadError):
                    raise
                raise HisReadError("HIS_READ_001", "Today's HIS index cannot be built.") from error

    def _set_index_status(
        self,
        state: str,
        progress: int,
        message: str,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
        phase: str | None = None,
        processed: int | None = None,
        total: int | None = None,
        progress_mode: str | None = None,
    ) -> None:
        with self._index_status_lock:
            self._today_index_state = state
            self._today_index_progress = max(0, min(100, progress))
            self._today_index_message = message
            if started_at is not None:
                self._today_index_started_at = started_at
            if completed_at is not None:
                self._today_index_completed_at = completed_at
            self._today_index_error = error
            if phase is not None:
                self._today_index_phase = phase
            if processed is not None:
                self._today_index_processed = max(0, processed)
            if total is not None:
                self._today_index_total = max(0, total)
            if progress_mode is not None:
                self._today_index_progress_mode = progress_mode
            self._today_index_updated_at = datetime.now()

    def _report_index_phase(
        self,
        *,
        phase: str,
        processed: int,
        total: int,
        start: int,
        end: int,
        message: str,
    ) -> None:
        self._set_index_status(
            "building",
            _phase_progress(processed, total, start, end),
            message,
            phase=phase,
            processed=processed,
            total=total,
            progress_mode="determinate" if total else "indeterminate",
        )

    def _reset_today_index_state(self, today: date) -> None:
        self._today_index_date = today
        self._today_index_by_doctor = {}
        self._today_index_signatures = {}
        self._today_index_cursors = {}
        self._today_index_headers_by_key = {}
        self._today_index_headers_by_relkey = {}
        self._today_index_items = []
        self._today_index_pending_items = []
        self._today_index_patients_by_key = {}
        self._today_index_inventory_by_item = {}
        with self._index_status_lock:
            self._today_index_started_at = None
            self._today_index_completed_at = None
            self._today_index_first_completed_at = None
            self._today_index_error = None
            self._today_index_phase = "idle"
            self._today_index_processed = 0
            self._today_index_total = 0
            self._today_index_progress_mode = "determinate"
        self._set_index_status("not_started", 0, "尚未建立今日索引", completed_at=None, error=None)

    def _build_today_index(self, report_date: date) -> dict[str, object]:
        if self.mirror_path is None:
            raise HisReadError("HIS_READ_001", "HIS mirror is not configured.")
        if not self.mirror_path.exists() or not self.mirror_path.is_dir():
            raise HisReadError("HIS_READ_001", "Configured HIS mirror cannot be read.")

        headers_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        headers_by_relkey: dict[str, list[dict[str, object]]] = {}
        header_total = _table_record_count(self._find_table("CH011M1"))
        self._report_index_phase(
            phase="headers",
            processed=0,
            total=header_total,
            start=0,
            end=30,
            message="正在讀取今日處方主檔",
        )
        header_step = _progress_step(header_total)
        for index, header in enumerate(self._iter_table("CH011M1"), start=1):
            if index % header_step == 0 or index == header_total:
                self._report_index_phase(
                    phase="headers",
                    processed=index,
                    total=header_total,
                    start=0,
                    end=30,
                    message="正在讀取今日處方主檔",
                )
            if _parse_date(_value(header, "SDATE", "REPORT_DATE", "DATE")) != report_date:
                continue
            key = _join_key(header)
            if key != ("", ""):
                headers_by_key.setdefault(key, []).append(header)
            relkey = _text(_value(header, "RELKEY", "REL_KEY"))
            if relkey:
                headers_by_relkey.setdefault(relkey, []).append(header)
        item_total = _table_record_count(self._find_table("CH012M1"))
        self._report_index_phase(
            phase="items",
            processed=0,
            total=item_total,
            start=30,
            end=80,
            message="正在配對抗病毒處方",
        )

        items: list[tuple[dict[str, object], MedicationMapping, str]] = []
        pending_items: list[tuple[dict[str, object], MedicationMapping, str]] = []
        inventory_by_item: dict[str, dict[str, object]] = {}
        inventory_loaded = False
        item_step = _progress_step(item_total)
        for index, item in enumerate(self._iter_table("CH012M1"), start=1):
            if index % item_step == 0 or index == item_total:
                self._report_index_phase(
                    phase="items",
                    processed=index,
                    total=item_total,
                    start=30,
                    end=80,
                    message="正在配對抗病毒處方",
                )
            mapping = self._mapping_for_item(item, inventory_by_item, inventory_loaded)
            if mapping is None and not inventory_loaded:
                inventory_by_item = {
                    _text(_value(row, "ITEMN", "ITEM_NO", "ITEMNO")): row
                    for row in self._iter_table("H_INV", required=False)
                }
                inventory_loaded = True
                mapping = self._mapping_for_item(item, inventory_by_item, inventory_loaded)
            if mapping is None:
                continue
            header = _choose_header(headers_by_key, headers_by_relkey, item)
            treat = _text(_value(item, "TREAT")) or _text(_value(header or {}, "TREAT"))
            if treat and treat not in {"Y", "C", "N"}:
                continue
            candidate = (item, mapping, treat)
            if header:
                items.append(candidate)

        all_headers = [
            header
            for groups in list(headers_by_key.values()) + list(headers_by_relkey.values())
            for header in groups
        ]
        patient_keys = {
            _patient_key(header)
            for header in all_headers
            if _patient_key(header) != ("", "")
        }
        candidate_keys = {
            _patient_key(header)
            for item, _, _ in items
            for header in [_choose_header(headers_by_key, headers_by_relkey, item)]
            if header is not None and _patient_key(header) != ("", "")
        }
        patient_keys |= candidate_keys
        patients_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        patient_total = _table_record_count(self._find_table("PD011M1"))
        self._report_index_phase(
            phase="patients",
            processed=0,
            total=patient_total,
            start=80,
            end=95,
            message="正在補齊病人資料",
        )
        patient_step = _progress_step(patient_total)
        for index, patient in enumerate(self._iter_table("PD011M1"), start=1):
            key = _patient_key(patient)
            if key in patient_keys:
                patients_by_key.setdefault(key, []).append(patient)
            if index % patient_step == 0 or index == patient_total:
                self._report_index_phase(
                    phase="patients",
                    processed=index,
                    total=patient_total,
                    start=80,
                    end=95,
                    message="正在補齊病人資料",
                )

        self._set_index_status(
            "building",
            95,
            "正在整理今日索引",
            phase="finalize",
            processed=0,
            total=0,
            progress_mode="indeterminate",
        )
        prescriptions = _materialize_index_prescriptions(
            items,
            headers_by_key,
            headers_by_relkey,
            patients_by_key,
        )
        cursors = self._capture_index_cursors()
        return {
            "headers_by_key": headers_by_key,
            "headers_by_relkey": headers_by_relkey,
            "items": items,
            "pending_items": pending_items,
            "patients_by_key": patients_by_key,
            "inventory_by_item": inventory_by_item,
            "prescriptions": prescriptions,
            "cursors": cursors,
        }

    def _mapping_for_item(
        self,
        item: dict[str, object],
        inventory_by_item: dict[str, dict[str, object]],
        inventory_loaded: bool,
    ) -> MedicationMapping | None:
        mapping = find_medication_mapping(
            med1=_value(item, "MED1", "MEDICATION", "DRUG"),
            itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
            labnum="",
            mappings=self.mappings,
        )
        if mapping is not None or not inventory_loaded:
            return mapping
        inventory_row = inventory_by_item.get(
            _text(_value(item, "ITEMN", "ITEM_NO", "ITEMNO")),
            {},
        )
        return find_medication_mapping(
            med1=_value(item, "MED1", "MEDICATION", "DRUG"),
            itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
            labnum=_value(inventory_row, "LABNUM", "LAB_NO", "NHI_CODE"),
            mappings=self.mappings,
        )

    def _refresh_today_index_if_needed(self) -> None:
        with self._index_lock:
            current = self._capture_index_cursors()
            previous = self._today_index_cursors
            if _cursors_equal(previous, current):
                return
            if not self._can_increment_index(previous, current):
                self._set_index_status(
                    "stale",
                    0,
                    "今日索引需要完整更新",
                    phase="stale",
                    processed=0,
                    total=0,
                    progress_mode="determinate",
                    error=None,
                )
                raise HisIndexStale()
            self._increment_today_index(previous, current)

    def _increment_today_index(
        self,
        previous: dict[str, _DbfCursor | None],
        current: dict[str, _DbfCursor | None],
    ) -> None:
        with self._index_status_lock:
            self._today_index_completed_at = None
        self._set_index_status(
            "building",
            0,
            "正在讀取新增資料",
            started_at=datetime.now(),
            phase="incremental_read",
            processed=0,
            total=0,
            progress_mode="indeterminate",
        )
        new_headers = list(self._iter_appended_table("CH011M1", previous["CH011M1"], current["CH011M1"]))
        new_items = list(self._iter_appended_table("CH012M1", previous["CH012M1"], current["CH012M1"]))
        new_patients = list(self._iter_appended_table("PD011M1", previous["PD011M1"], current["PD011M1"]))
        incremental_total = len(new_headers) + len(new_items) + len(new_patients)
        self._set_index_status(
            "building",
            0,
            "正在快速更新今日索引",
            phase="incremental_headers",
            processed=0,
            total=incremental_total,
            progress_mode="determinate" if incremental_total else "indeterminate",
        )

        for header in new_headers:
            if _parse_date(_value(header, "SDATE", "REPORT_DATE", "DATE")) != self._today_index_date:
                continue
            key = _join_key(header)
            if key != ("", ""):
                self._today_index_headers_by_key.setdefault(key, []).append(header)
            relkey = _text(_value(header, "RELKEY", "REL_KEY"))
            if relkey:
                self._today_index_headers_by_relkey.setdefault(relkey, []).append(header)
        self._set_index_status(
            "building",
            _phase_progress(len(new_headers), incremental_total, 0, 30),
            "正在快速更新今日索引",
            phase="incremental_items",
            processed=len(new_headers),
            total=incremental_total,
            progress_mode="determinate" if incremental_total else "indeterminate",
        )

        for item in new_items:
            mapping = self._mapping_for_item(
                item,
                self._today_index_inventory_by_item,
                bool(self._today_index_inventory_by_item),
            )
            if mapping is None:
                continue
            header = _choose_header(
                self._today_index_headers_by_key,
                self._today_index_headers_by_relkey,
                item,
            )
            treat = _text(_value(item, "TREAT")) or _text(_value(header or {}, "TREAT"))
            if treat and treat not in {"Y", "C", "N"}:
                continue
            candidate = (item, mapping, treat)
            if header:
                self._today_index_items.append(candidate)
            else:
                self._today_index_pending_items.append(candidate)

        processed_after_items = len(new_headers) + len(new_items)
        self._set_index_status(
            "building",
            _phase_progress(processed_after_items, incremental_total, 30, 70),
            "正在快速更新今日索引",
            phase="incremental_patients",
            processed=processed_after_items,
            total=incremental_total,
            progress_mode="determinate" if incremental_total else "indeterminate",
        )

        still_pending: list[tuple[dict[str, object], MedicationMapping, str]] = []
        for item, mapping, treat in self._today_index_pending_items:
            if _choose_header(
                self._today_index_headers_by_key,
                self._today_index_headers_by_relkey,
                item,
            ):
                self._today_index_items.append((item, mapping, treat))
            else:
                still_pending.append((item, mapping, treat))
        self._today_index_pending_items = still_pending

        candidate_keys = {
            _patient_key(header)
            for item, _, _ in self._today_index_items
            for header in [
                _choose_header(
                    self._today_index_headers_by_key,
                    self._today_index_headers_by_relkey,
                    item,
                )
            ]
            if header is not None and _patient_key(header) != ("", "")
        }
        for patient in new_patients:
            key = _patient_key(patient)
            if key in candidate_keys:
                self._today_index_patients_by_key.setdefault(key, []).append(patient)

        processed_after_patients = processed_after_items + len(new_patients)
        self._set_index_status(
            "building",
            _phase_progress(processed_after_patients, incremental_total, 70, 90),
            "正在快速更新今日索引",
            phase="incremental_finalize",
            processed=processed_after_patients,
            total=incremental_total,
            progress_mode="determinate" if incremental_total else "indeterminate",
        )

        # A new header can legitimately reference a patient row that was
        # already present before this index snapshot.  Usually the patient
        # row is appended alongside the order, but resolve this edge case
        # from the read-only table before materialising the candidate rather
        # than silently dropping its identity fields.
        missing_patient_keys = {
            key for key in candidate_keys if key not in self._today_index_patients_by_key
        }
        if missing_patient_keys:
            for patient in self._iter_table("PD011M1"):
                key = _patient_key(patient)
                if key in missing_patient_keys:
                    self._today_index_patients_by_key.setdefault(key, []).append(patient)

        prescriptions = _materialize_index_prescriptions(
            self._today_index_items,
            self._today_index_headers_by_key,
            self._today_index_headers_by_relkey,
            self._today_index_patients_by_key,
        )
        self._today_index_by_doctor = _group_by_doctor(prescriptions)
        self._today_index_cursors = current
        self._today_index_signatures = {
            table_name: cursor.signature if cursor else None
            for table_name, cursor in current.items()
        }
        self._today_cache.clear()
        self._set_index_status(
            "ready",
            100,
            "今日索引已快速更新",
            completed_at=datetime.now(),
            phase="ready",
            processed=incremental_total,
            total=incremental_total,
            progress_mode="determinate",
        )

    def _can_increment_index(
        self,
        previous: dict[str, _DbfCursor | None],
        current: dict[str, _DbfCursor | None],
    ) -> bool:
        for table_name in ("CH011M1", "CH012M1", "PD011M1"):
            old = previous.get(table_name)
            new = current.get(table_name)
            if old is None or new is None:
                return False
            if (
                old.record_length != new.record_length
                or old.header_length != new.header_length
                or new.num_records < old.num_records
            ):
                return False
            if new.num_records == old.num_records:
                if new.signature != old.signature:
                    return False
                continue
            if not _dbf_has_expected_size(new):
                return False
            if not _dbf_tail_unchanged(self._find_table(table_name), old):
                return False
        old_inventory = previous.get("H_INV")
        new_inventory = current.get("H_INV")
        return old_inventory == new_inventory

    def _capture_index_cursors(self) -> dict[str, _DbfCursor | None]:
        return {
            # The streaming read above is the required-source check.  A
            # subclass/test seam may provide rows without real DBF paths;
            # represent those tables as unknown cursors rather than failing
            # after the index itself was built.
            table_name: _read_dbf_cursor(self._find_table(table_name), required=False)
            for table_name in ("CH011M1", "CH012M1", "PD011M1", "H_INV")
        }

    def _iter_appended_table(
        self,
        table_name: str,
        previous: _DbfCursor | None,
        current: _DbfCursor | None,
    ) -> Iterator[dict[str, object]]:
        if previous is None or current is None or current.num_records <= previous.num_records:
            return
        yield from self._iter_table_from_record(
            table_name,
            previous.num_records,
            end_record=current.num_records,
        )

    def _iter_table_from_record(
        self,
        table_name: str,
        start_record: int,
        *,
        end_record: int | None = None,
    ) -> Iterator[dict[str, object]]:
        path = self._find_table(table_name)
        if path is None:
            raise HisReadError("HIS_READ_001", f"HIS source table {table_name} is missing.")
        try:
            table = DBF(
                str(path),
                load=False,
                ignore_missing_memofile=True,
                char_decode_errors="ignore",
            )
            if start_record >= table.header.numrecords:
                return
            with open(table.filename, "rb") as infile, table._open_memofile() as memofile:
                infile.seek(table.header.headerlen + start_record * table.header.recordlen, 0)
                parser = None if table.raw else table.parserclass(table, memofile)
                record_limit = min(
                    table.header.numrecords,
                    end_record if end_record is not None else table.header.numrecords,
                )
                for _ in range(start_record, record_limit):
                    marker = infile.read(1)
                    if marker in (b"\x1a", b""):
                        break
                    if marker == b" ":
                        if table.raw:
                            items = [(field.name, infile.read(field.length)) for field in table.fields]
                        else:
                            items = [
                                (field.name, parser.parse(field, infile.read(field.length)))
                                for field in table.fields
                            ]
                        yield {str(key).upper(): value for key, value in table.recfactory(items).items()}
                    else:
                        infile.seek(table.header.recordlen - 1, 1)
        except (OSError, ValueError, RuntimeError) as error:
            raise HisReadError("HIS_READ_001", f"HIS source table {table_name} cannot be read.") from error

    def _prescriptions_for_day(self, report_date: date, doctor_id: str) -> list[Prescription]:
        """Read only one doctor's prescriptions for one date.

        CH011M1 is filtered before CH012M1 is scanned.  The DBF reader still
        may need to walk the network file when an xBase index is unavailable,
        but it does not materialize historical orders or unrelated doctors.
        """
        if self.mirror_path is None:
            raise HisReadError("HIS_READ_001", "HIS mirror is not configured.")
        if not self.mirror_path.exists() or not self.mirror_path.is_dir():
            raise HisReadError("HIS_READ_001", "Configured HIS mirror cannot be read.")

        cache_key = (report_date, doctor_id)
        cached = self._today_cache.get(cache_key)
        if cached is not None and self._signatures_are_current(cached[0]):
            return cached[1]

        headers_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        headers_by_relkey: dict[str, list[dict[str, object]]] = {}
        for header in self._iter_table("CH011M1"):
            if _parse_date(_value(header, "SDATE", "REPORT_DATE", "DATE")) != report_date:
                continue
            if _text(_value(header, "DOC", "DR_ID", "DOC1", "DOCID", "DOCTORID", "DOCNO", "DOCTOR", "PHYSICIAN")) != doctor_id:
                continue
            key = _join_key(header)
            if key != ("", ""):
                headers_by_key.setdefault(key, []).append(header)
            relkey = _text(_value(header, "RELKEY", "REL_KEY"))
            if relkey:
                headers_by_relkey.setdefault(relkey, []).append(header)

        used_tables = {"CH011M1", "CH012M1"}
        if not headers_by_key and not headers_by_relkey:
            prescriptions: list[Prescription] = []
            self._cache_today(cache_key, used_tables, prescriptions)
            return prescriptions

        candidates: list[tuple[dict[str, object], dict[str, object], MedicationMapping, str]] = []
        inventory_by_item: dict[str, dict[str, object]] = {}
        inventory_loaded = False
        for item in self._iter_table("CH012M1"):
            header = _choose_header(headers_by_key, headers_by_relkey, item)
            if not header:
                continue
            mapping = find_medication_mapping(
                med1=_value(item, "MED1", "MEDICATION", "DRUG"),
                itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
                labnum="",
                mappings=self.mappings,
            )
            if mapping is None and not inventory_loaded:
                inventory_by_item = {
                    _text(_value(row, "ITEMN", "ITEM_NO", "ITEMNO")): row
                    for row in self._iter_table("H_INV", required=False)
                }
                inventory_loaded = True
                used_tables.add("H_INV")
            if mapping is None:
                inventory_row = inventory_by_item.get(
                    _text(_value(item, "ITEMN", "ITEM_NO", "ITEMNO")),
                    {},
                )
                mapping = find_medication_mapping(
                    med1=_value(item, "MED1", "MEDICATION", "DRUG"),
                    itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
                    labnum=_value(inventory_row, "LABNUM", "LAB_NO", "NHI_CODE"),
                    mappings=self.mappings,
                )
            if mapping is None:
                continue
            treat = _text(_value(item, "TREAT")) or _text(_value(header, "TREAT"))
            if treat and treat not in {"Y", "C", "N"}:
                continue
            candidates.append((item, header, mapping, treat))

        patients_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        if candidates:
            used_tables.add("PD011M1")
            patient_keys = {
                _patient_key(header)
                for _, header, _, _ in candidates
                if _patient_key(header) != ("", "")
            }
            for patient in self._iter_table("PD011M1"):
                key = _patient_key(patient)
                if key in patient_keys:
                    patients_by_key.setdefault(key, []).append(patient)

        prescriptions = []
        for item, header, mapping, treat in candidates:
            patient = _choose_patient(patients_by_key, header)
            try:
                prescription = _normalise_prescription(item, header, mapping, treat, patient=patient)
                if not (
                    prescription.patient_name
                    and prescription.medical_record_number
                    and prescription.patient_id
                ):
                    continue
                prescriptions.append(prescription)
            except (ValueError, TypeError, InvalidOperation):
                continue
        self._cache_today(cache_key, used_tables, prescriptions)
        return prescriptions

    def _read_selected_order(self, source_id: str) -> Prescription | None:
        if self.mirror_path is None:
            raise HisReadError("HIS_READ_001", "HIS mirror is not configured.")
        if not self.mirror_path.exists() or not self.mirror_path.is_dir():
            raise HisReadError("HIS_READ_001", "Configured HIS mirror cannot be read.")

        source_parts = source_id.split("|")
        relkey_hint = source_parts[0] if source_parts else ""
        candidate_items: list[dict[str, object]] = []
        for item in self._iter_table("CH012M1"):
            if relkey_hint and _text(_value(item, "RELKEY", "REL_KEY")) != relkey_hint:
                continue
            if _source_id(item, {}) == source_id:
                candidate_items.append(item)
        if not candidate_items:
            return None

        headers_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        headers_by_relkey: dict[str, list[dict[str, object]]] = {}
        for header in self._iter_table("CH011M1"):
            relkey = _text(_value(header, "RELKEY", "REL_KEY"))
            if relkey_hint and relkey != relkey_hint:
                continue
            key = _join_key(header)
            if key != ("", ""):
                headers_by_key.setdefault(key, []).append(header)
            if relkey:
                headers_by_relkey.setdefault(relkey, []).append(header)

        selected: list[tuple[dict[str, object], dict[str, object]]] = []
        for item in candidate_items:
            header = _choose_header(headers_by_key, headers_by_relkey, item)
            if header is not None and _source_id(item, header) == source_id:
                selected.append((item, header))
        if len(selected) != 1:
            return None
        item, header = selected[0]

        mapping = find_medication_mapping(
            med1=_value(item, "MED1", "MEDICATION", "DRUG"),
            itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
            labnum="",
            mappings=self.mappings,
        )
        if mapping is None:
            inventory_by_item = {
                _text(_value(row, "ITEMN", "ITEM_NO", "ITEMNO")): row
                for row in self._iter_table("H_INV", required=False)
            }
            inventory_row = inventory_by_item.get(
                _text(_value(item, "ITEMN", "ITEM_NO", "ITEMNO")),
                {},
            )
            mapping = find_medication_mapping(
                med1=_value(item, "MED1", "MEDICATION", "DRUG"),
                itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
                labnum=_value(inventory_row, "LABNUM", "LAB_NO", "NHI_CODE"),
                mappings=self.mappings,
            )
        if mapping is None:
            return None

        treat = _text(_value(item, "TREAT")) or _text(_value(header, "TREAT"))
        if treat and treat not in {"Y", "C", "N"}:
            return None

        patients_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        patient_key = _patient_key(header)
        if patient_key != ("", ""):
            for patient in self._iter_table("PD011M1"):
                if _patient_key(patient) == patient_key:
                    patients_by_key.setdefault(patient_key, []).append(patient)
        patient = _choose_patient(patients_by_key, header)
        try:
            prescription = _normalise_prescription(item, header, mapping, treat, patient=patient)
        except (ValueError, TypeError, InvalidOperation):
            return None
        if prescription.source_id != source_id:
            return None
        if not (
            prescription.patient_name
            and prescription.medical_record_number
            and prescription.patient_id
        ):
            return None
        return prescription

    def _cache_today(
        self,
        cache_key: tuple[date, str],
        table_names: set[str],
        prescriptions: list[Prescription],
    ) -> None:
        signatures = {
            table_name: _file_signature(self._find_table(table_name))
            for table_name in table_names
        }
        self._today_cache[cache_key] = (signatures, prescriptions)

    def _signatures_are_current(self, signatures: dict[str, tuple[int, int] | None]) -> bool:
        return all(
            _file_signature(self._find_table(table_name)) == signature
            for table_name, signature in signatures.items()
        )

    def _read_table(self, table_name: str, *, required: bool = True) -> list[dict[str, object]]:
        cache_key = table_name.upper()
        path = self._find_table(cache_key)
        if path is None:
            if required:
                raise HisReadError("HIS_READ_001", f"HIS source table {table_name} is missing.")
            return []
        signature = _file_signature(path)
        cached = self._table_cache.get(cache_key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        try:
            table = DBF(
                str(path),
                # Materialize once so the application cache can serve subsequent lookups
                # without reopening the network DBF stream for every page request.
                load=True,
                ignore_missing_memofile=True,
                char_decode_errors="ignore",
            )
            rows = [{str(key).upper(): value for key, value in row.items()} for row in table]
            if signature is not None:
                self._table_cache[cache_key] = (signature, rows)
            return rows
        except (OSError, ValueError, RuntimeError) as error:
            raise HisReadError("HIS_READ_001", f"HIS source table {table_name} cannot be read.") from error

    def _iter_table(self, table_name: str, *, required: bool = True) -> Iterator[dict[str, object]]:
        path = self._find_table(table_name)
        if path is None:
            if required:
                raise HisReadError("HIS_READ_001", f"HIS source table {table_name} is missing.")
            return
        try:
            # dbfread opens the production DBF in read mode only.  This path
            # deliberately streams rows and never writes DBF/FPT/CDX files.
            table = DBF(
                str(path),
                load=False,
                ignore_missing_memofile=True,
                char_decode_errors="ignore",
            )
            for row in table:
                yield {str(key).upper(): value for key, value in row.items()}
        except (OSError, ValueError, RuntimeError) as error:
            raise HisReadError("HIS_READ_001", f"HIS source table {table_name} cannot be read.") from error

    def _find_table(self, table_name: str) -> Path | None:
        if self.mirror_path is None:
            return None
        cache_key = table_name.casefold()
        self._discover_table_paths()
        return self._table_paths.get(cache_key)

    def _discover_table_paths(self) -> None:
        if self._table_paths_discovered or self.mirror_path is None:
            return
        # Production keeps the known source tables in DATA.  Restrict lookup
        # to that directory (and a flat mirror root) instead of recursively
        # enumerating the whole HIS share, which also contains application
        # archives and unrelated DBF files.
        roots = [self.mirror_path / "DATA", self.mirror_path]
        known_tables = ("CH012M1", "CH011M1", "PD011M1", "H_INV")
        for root in roots:
            try:
                if not root.is_dir():
                    continue
                for table_name in known_tables:
                    for suffix in (".DBF", ".dbf"):
                        path = root / f"{table_name}{suffix}"
                        if path.is_file():
                            self._table_paths.setdefault(table_name.casefold(), path)
                            break
            except OSError:
                continue
        self._table_paths_discovered = True

    def _cache_is_current(self) -> bool:
        return all(
            _file_signature(self._table_paths.get(table_name.casefold())) == signature
            for table_name, signature in self._prescription_cache_signatures.items()
        )


def _normalise_prescription(
    item: dict[str, object],
    header: dict[str, object],
    mapping: MedicationMapping,
    treat: str,
    *,
    patient: dict[str, object] | None = None,
) -> Prescription:
    report_date = _parse_date(_value(header, "SDATE", "REPORT_DATE", "DATE"))
    if report_date is None:
        raise ValueError("Missing report date")
    source_id = _source_id(item, header)
    quantity = _quantity(_value(item, mapping.source_quantity_field, "USE_TAMT", "QTY", "QUANTITY"))
    patient = patient or {}
    return Prescription(
        source_id=source_id,
        medical_record_number=_text(
            _value(patient, "NUM", "MRN", "CHARTNO", "CHART_NO", "PATNO", "REGNO")
            or _value(header, "NUM", "MRN", "CHARTNO", "CHART_NO", "PATNO", "REGNO")
        ),
        patient_name=_text(
            _value(patient, "NAME", "PATNAME", "PATIENT_NAME", "PNAME")
            or _value(header, "PATNAME", "PATIENT_NAME", "PNAME", "NAME")
        ),
        patient_id=_text(
            _value(patient, "ID", "PATIENTID", "PATIENT_ID", "PID", "IDNO")
            or _value(header, "ID", "PATIENTID", "PATIENT_ID", "PID", "IDNO")
        ),
        birth_date=_parse_date(
            _value(patient, "BIRTHDATE", "BIRTH", "BDATE")
            or _value(header, "BIRTHDATE", "BIRTH", "BDATE")
        ),
        sex=_text(_value(patient, "SEX", "GENDER") or _value(header, "SEX", "GENDER")),
        report_date=report_date,
        # CH011M1 uses DOC for the physician code in the production HIS.
        doctor_id=_text(
            _value(header, "DOC", "DR_ID", "DOC1", "DOCID", "DOCTORID", "DOCNO", "DOCTOR", "PHYSICIAN")
        ),
        medication_id=mapping.id,
        medication_name=mapping.display_name,
        official_material=mapping.official_material,
        unit=mapping.unit,
        source_quantity=quantity,
        treat=treat,
        report_time=_parse_time(_value(header, "STIME", "REPORT_TIME", "TIME")),
    )


def _materialize_index_prescriptions(
    items: Iterable[tuple[dict[str, object], MedicationMapping, str]],
    headers_by_key: dict[tuple[str, str], list[dict[str, object]]],
    headers_by_relkey: dict[str, list[dict[str, object]]],
    patients_by_key: dict[tuple[str, str], list[dict[str, object]]],
) -> list[Prescription]:
    prescriptions: list[Prescription] = []
    for item, mapping, treat in items:
        header = _choose_header(headers_by_key, headers_by_relkey, item)
        if not header:
            continue
        patient = _choose_patient(patients_by_key, header)
        try:
            prescription = _normalise_prescription(item, header, mapping, treat, patient=patient)
            if not (
                prescription.patient_name
                and prescription.medical_record_number
                and prescription.patient_id
            ):
                continue
            prescriptions.append(prescription)
        except (ValueError, TypeError, InvalidOperation):
            continue
    return _sort_prescriptions(prescriptions)


def _group_by_doctor(items: Iterable[Prescription]) -> dict[str, list[Prescription]]:
    grouped: dict[str, list[Prescription]] = {}
    for item in items:
        grouped.setdefault(item.doctor_id, []).append(item)
    for doctor_id, prescriptions in grouped.items():
        grouped[doctor_id] = _sort_prescriptions(prescriptions)
    return grouped


def _choose_header(
    headers_by_key: dict[tuple[str, str], list[dict[str, object]]],
    headers_by_relkey: dict[str, list[dict[str, object]]],
    item: dict[str, object],
) -> dict[str, object] | None:
    candidates = headers_by_key.get(_join_key(item), [])
    if candidates:
        return candidates[0]
    relkey = _text(_value(item, "RELKEY", "REL_KEY"))
    if relkey:
        candidates = headers_by_relkey.get(relkey, [])
        if candidates:
            return candidates[0]
    return None


def _source_id(item: dict[str, object], header: dict[str, object]) -> str:
    values = [
        _text(_value(item, "RELKEY", "REL_KEY") or _value(header, "RELKEY", "REL_KEY")),
        _text(_value(item, "SYS_2015", "SYS2015") or _value(header, "SYS_2015", "SYS2015")),
        _text(_value(item, "ITEMSEQ", "ITEM_SEQ", "ITEMNO", "SEQ", "MEDSEQ", "MED_SEQ")),
        _text(_value(item, "MED1", "MEDICATION", "DRUG")),
    ]
    values = [value for value in values if value]
    if not values:
        raise ValueError("Missing stable source identity")
    return "|".join(values)


def _join_key(row: dict[str, object]) -> tuple[str, str]:
    return (
        _text(_value(row, "RELKEY", "REL_KEY")),
        _text(_value(row, "SYS_2015", "SYS2015")),
    )


def _patient_key(row: dict[str, object]) -> tuple[str, str]:
    return (
        _text(_value(row, "ID", "PATIENTID", "PATIENT_ID", "PID", "IDNO")),
        _text(_value(row, "NUM", "MRN", "CHARTNO", "CHART_NO", "PATNO", "REGNO")),
    )


def _choose_patient(
    patients_by_key: dict[tuple[str, str], list[dict[str, object]]],
    header: dict[str, object],
) -> dict[str, object] | None:
    candidates = patients_by_key.get(_patient_key(header), [])
    return candidates[0] if len(candidates) == 1 else None


def _value(row: dict[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name.upper())
        if value not in (None, ""):
            return value
    return ""


def _text(value: object) -> str:
    return str(value or "").strip()


def _file_signature(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _table_record_count(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        table = DBF(
            str(path),
            load=False,
            ignore_missing_memofile=True,
            char_decode_errors="ignore",
        )
        return int(table.header.numrecords)
    except (OSError, ValueError, RuntimeError):
        return 0


def _progress_step(total: int) -> int:
    """Keep status updates frequent enough for a live UI without per-row locks."""
    return max(25, total // 200) if total else 25


def _phase_progress(processed: int, total: int, start: int, end: int) -> int:
    if total <= 0:
        return start
    ratio = min(1.0, max(0.0, processed / total))
    return start + int(round((end - start) * ratio))


def _read_dbf_cursor(path: Path | None, *, required: bool) -> _DbfCursor | None:
    if path is None:
        if required:
            raise HisReadError("HIS_READ_001", "Configured HIS table is missing.")
        return None
    try:
        table = DBF(
            str(path),
            load=False,
            ignore_missing_memofile=True,
            char_decode_errors="ignore",
        )
        signature = _file_signature(path)
        return _DbfCursor(
            signature=signature,
            num_records=int(table.header.numrecords),
            record_length=int(table.header.recordlen),
            header_length=int(table.header.headerlen),
            tail_digest=_dbf_record_digest(
                path,
                int(table.header.headerlen),
                int(table.header.recordlen),
                int(table.header.numrecords) - 1,
            ),
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise HisReadError("HIS_READ_001", "Configured HIS table cannot be inspected.") from error


def _dbf_record_digest(
    path: Path,
    header_length: int,
    record_length: int,
    record_index: int,
) -> str | None:
    if record_index < 0:
        return None
    try:
        with open(path, "rb") as source:
            source.seek(header_length + record_index * record_length, 0)
            payload = source.read(record_length)
        if len(payload) != record_length:
            return None
        return hashlib.sha256(payload).hexdigest()
    except OSError:
        return None


def _dbf_has_expected_size(cursor: _DbfCursor) -> bool:
    if cursor.signature is None:
        return False
    return cursor.signature[1] == cursor.header_length + cursor.num_records * cursor.record_length + 1


def _dbf_tail_unchanged(path: Path | None, previous: _DbfCursor) -> bool:
    if path is None:
        return False
    return (
        _dbf_record_digest(path, previous.header_length, previous.record_length, previous.num_records - 1)
        == previous.tail_digest
    )


def _cursors_equal(
    previous: dict[str, _DbfCursor | None],
    current: dict[str, _DbfCursor | None],
) -> bool:
    return all(previous.get(name) == current.get(name) for name in current)


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for format_string in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], format_string).date()
        except ValueError:
            continue
    return None


def _parse_time(value: object) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = _text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit() and len(text) <= 4:
        text = text.zfill(4)
    for format_string in ("%H:%M:%S", "%H:%M", "%H%M%S", "%H%M"):
        try:
            return datetime.strptime(text[:8], format_string).time()
        except ValueError:
            continue
    return None


def _quantity(value: object) -> int:
    number = Decimal(str(value).strip())
    if number != number.to_integral_value():
        raise ValueError("Quantity must be a whole number")
    return int(number)


def _sort_prescriptions(items: Iterable[Prescription]) -> list[Prescription]:
    return sorted(
        items,
        key=lambda item: (
            item.report_date,
            item.report_time or time.min,
            item.source_id,
        ),
        reverse=True,
    )


def _validate_date_range(start_date: date, end_date: date) -> None:
    if end_date < start_date or (end_date - start_date).days + 1 > 31:
        raise DateRangeError()

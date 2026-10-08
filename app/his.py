from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Protocol

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

    def find_by_mrn(self, medical_record_number: str, doctor_id: str | None = None) -> list[Prescription]: ...

    def scan(self, start_date: date, end_date: date) -> list[Prescription]: ...

    def get(self, source_id: str) -> Prescription | None: ...


class InMemoryHisReader:
    """Small test and development seam with the same behavior as the DBF reader."""

    def __init__(self, prescriptions: Iterable[Prescription]):
        self._prescriptions = tuple(prescriptions)

    def most_recent(self, doctor_id: str) -> Prescription | None:
        matches = [item for item in self._prescriptions if item.doctor_id == doctor_id]
        return _sort_prescriptions(matches)[0] if matches else None

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

    def __init__(self, mirror_path: Path | None, mappings: Iterable[MedicationMapping] = PUBLIC_ANTIVIRALS):
        self.mirror_path = mirror_path
        self.mappings = tuple(mappings)

    def most_recent(self, doctor_id: str) -> Prescription | None:
        matches = [item for item in self._all_prescriptions() if item.doctor_id == doctor_id]
        return _sort_prescriptions(matches)[0] if matches else None

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
        return next((item for item in self._all_prescriptions() if item.source_id == source_id), None)

    def _all_prescriptions(self) -> list[Prescription]:
        if self.mirror_path is None:
            raise HisReadError("HIS_READ_001", "HIS mirror is not configured.")
        if not self.mirror_path.exists() or not self.mirror_path.is_dir():
            raise HisReadError("HIS_READ_001", "Configured HIS mirror cannot be read.")

        items = self._read_table("CH012M1")
        headers = self._read_table("CH011M1")
        inventory = self._read_table("H_INV", required=False)
        inventory_by_item = {
            _text(_value(row, "ITEMN", "ITEM_NO", "ITEMNO")): row for row in inventory
        }
        headers_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in headers:
            key = _join_key(row)
            if key != ("", ""):
                headers_by_key.setdefault(key, []).append(row)

        prescriptions: list[Prescription] = []
        for item in items:
            inventory_row = inventory_by_item.get(_text(_value(item, "ITEMN", "ITEM_NO", "ITEMNO")), {})
            mapping = find_medication_mapping(
                med1=_value(item, "MED1", "MEDICATION", "DRUG"),
                itemn=_value(item, "ITEMN", "ITEM_NO", "ITEMNO"),
                labnum=_value(inventory_row, "LABNUM", "LAB_NO", "NHI_CODE"),
                mappings=self.mappings,
            )
            if mapping is None:
                continue

            header = _choose_header(headers_by_key, item)
            if not header:
                continue
            treat = _text(_value(item, "TREAT")) or _text(_value(header, "TREAT"))
            if treat and treat not in {"Y", "C", "N"}:
                continue
            try:
                prescriptions.append(_normalise_prescription(item, header, mapping, treat))
            except (ValueError, TypeError, InvalidOperation):
                continue
        return prescriptions

    def _read_table(self, table_name: str, *, required: bool = True) -> list[dict[str, object]]:
        path = self._find_table(table_name)
        if path is None:
            if required:
                raise HisReadError("HIS_READ_001", f"HIS source table {table_name} is missing.")
            return []
        try:
            table = DBF(
                str(path),
                load=False,
                ignore_missing_memofile=True,
                char_decode_errors="ignore",
            )
            return [{str(key).upper(): value for key, value in row.items()} for row in table]
        except (OSError, ValueError, RuntimeError) as error:
            raise HisReadError("HIS_READ_001", f"HIS source table {table_name} cannot be read.") from error

    def _find_table(self, table_name: str) -> Path | None:
        if self.mirror_path is None:
            return None
        target = f"{table_name.casefold()}.dbf"
        for path in self.mirror_path.rglob("*"):
            if path.is_file() and path.name.casefold() == target:
                return path
        return None


def _normalise_prescription(
    item: dict[str, object],
    header: dict[str, object],
    mapping: MedicationMapping,
    treat: str,
) -> Prescription:
    report_date = _parse_date(_value(header, "SDATE", "REPORT_DATE", "DATE"))
    if report_date is None:
        raise ValueError("Missing report date")
    source_id = _source_id(item, header)
    quantity = _quantity(_value(item, mapping.source_quantity_field, "USE_TAMT", "QTY", "QUANTITY"))
    return Prescription(
        source_id=source_id,
        medical_record_number=_text(_value(header, "MRN", "CHARTNO", "CHART_NO", "PATNO", "REGNO")),
        patient_name=_text(_value(header, "PATNAME", "PATIENT_NAME", "PNAME", "NAME")),
        patient_id=_text(_value(header, "PATIENTID", "PATIENT_ID", "PID", "IDNO")),
        birth_date=_parse_date(_value(header, "BIRTHDATE", "BIRTH", "BDATE")),
        sex=_text(_value(header, "SEX", "GENDER")),
        report_date=report_date,
        doctor_id=_text(_value(header, "DOCID", "DOCTORID", "DOCNO", "DOCTOR", "PHYSICIAN")),
        medication_id=mapping.id,
        medication_name=mapping.display_name,
        official_material=mapping.official_material,
        unit=mapping.unit,
        source_quantity=quantity,
        treat=treat,
    )


def _choose_header(
    headers_by_key: dict[tuple[str, str], list[dict[str, object]]], item: dict[str, object]
) -> dict[str, object] | None:
    candidates = headers_by_key.get(_join_key(item), [])
    if candidates:
        return candidates[0]
    relkey = _text(_value(item, "RELKEY", "REL_KEY"))
    if relkey:
        for (candidate_relkey, _), rows in headers_by_key.items():
            if candidate_relkey == relkey and rows:
                return rows[0]
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


def _value(row: dict[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name.upper())
        if value not in (None, ""):
            return value
    return ""


def _text(value: object) -> str:
    return str(value or "").strip()


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


def _quantity(value: object) -> int:
    number = Decimal(str(value).strip())
    if number != number.to_integral_value():
        raise ValueError("Quantity must be a whole number")
    return int(number)


def _sort_prescriptions(items: Iterable[Prescription]) -> list[Prescription]:
    return sorted(items, key=lambda item: (item.report_date, item.source_id), reverse=True)


def _validate_date_range(start_date: date, end_date: date) -> None:
    if end_date < start_date or (end_date - start_date).days + 1 > 31:
        raise DateRangeError()

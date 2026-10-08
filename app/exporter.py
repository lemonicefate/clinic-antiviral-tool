from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook

from app.cases import EXCLUDED, LotAllocation
from app.database import CaseRecord
from app.template import TemplateCompatibilityError


class ExportError(RuntimeError):
    code = "EXPORT_002"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ExportSkip:
    case_id: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExportedWorkbook:
    path: Path
    row_count: int


@dataclass(frozen=True)
class ExportTable:
    sheet_name: str
    header_row: int
    columns: dict[str, int]


FIELD_ALIASES = {
    "source_id": {"sourceid", "source", "來源識別", "來源編號"},
    "medical_record_number": {"medicalrecordnumber", "mrn", "病歷號", "病歷號碼"},
    "patient_name": {"patientname", "姓名", "病患姓名"},
    "patient_id": {"patientid", "身分證字號", "身分證", "病人身分證"},
    "birth_date": {"birthdate", "出生日期", "出生年月日"},
    "sex": {"sex", "gender", "性別"},
    "report_date": {"reportdate", "usedate", "用藥日期", "使用日期", "回報日期"},
    "doctor_id": {"doctorid", "doctor", "醫師代號", "醫師"},
    "official_material": {"officialmaterial", "material", "藥品名稱", "藥品", "品項"},
    "reason_code": {"reasoncode", "用藥原因代碼", "用藥條件代碼", "使用條件代碼"},
    "reason_label": {"reasonlabel", "reason", "用藥原因", "用藥條件", "使用條件"},
    "actual_quantity": {"actualquantity", "quantity", "qty", "使用量", "實際數量", "回報數量"},
    "lot_number": {"lotnumber", "lot", "批號"},
    "lot_quantity": {"lotquantity", "allocationquantity", "批號數量", "分配數量"},
}

REQUIRED_EXPORT_FIELDS = {
    "medical_record_number",
    "patient_name",
    "report_date",
    "doctor_id",
    "official_material",
    "reason_code",
    "actual_quantity",
    "lot_number",
}


def validate_case_for_export(case: CaseRecord) -> tuple[str, ...]:
    reasons: list[str] = []
    if case.state == EXCLUDED:
        reasons.append("case is excluded")
    if not case.reason_code:
        reasons.append("missing medication-use reason")
    if case.actual_quantity is None or case.actual_quantity <= 0:
        reasons.append("actual quantity is missing or invalid")
    if not case.lots:
        reasons.append("missing lot")
    elif case.actual_quantity is not None and sum(lot.quantity for lot in case.lots) != case.actual_quantity:
        reasons.append("lot quantities do not equal actual quantity")
    for field_name, value in (
        ("medical record number", case.medical_record_number),
        ("patient name", case.patient_name),
        ("report date", case.report_date),
        ("doctor ID", case.doctor_id),
        ("official material", case.official_material),
    ):
        if not value:
            reasons.append(f"missing {field_name}")
    return tuple(reasons)


def export_cases(
    template_path: Path,
    output_path: Path,
    cases: Iterable[CaseRecord],
) -> ExportedWorkbook:
    cases = tuple(cases)
    if not template_path.exists() or not template_path.is_file():
        raise TemplateCompatibilityError("The official Excel template is missing.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(template_path, output_path)
        workbook = load_workbook(output_path)
        table = find_export_table(workbook)
        rows = []
        for case in cases:
            for lot in case.lots:
                rows.append((case, lot))
        written_rows: list[int] = []
        row_number = _first_empty_row(workbook[table.sheet_name], table)
        for case, lot in rows:
            _write_case_row(workbook[table.sheet_name], row_number, table, case, lot)
            written_rows.append(row_number)
            row_number += 1
        workbook.save(output_path)
        workbook.close()
        _validate_generated_workbook(output_path, table, cases, written_rows)
        return ExportedWorkbook(path=output_path, row_count=len(rows))
    except TemplateCompatibilityError:
        output_path.unlink(missing_ok=True)
        raise
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise ExportError("The Excel workbook could not be generated.") from error


def find_export_table(workbook) -> ExportTable:
    for sheet in workbook.worksheets:
        for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            columns: dict[str, int] = {}
            for column_number, value in enumerate(row, start=1):
                header = _normalise_header(value)
                for field_name, aliases in FIELD_ALIASES.items():
                    if header in {_normalise_header(alias) for alias in aliases} and field_name not in columns:
                        columns[field_name] = column_number
            if REQUIRED_EXPORT_FIELDS.issubset(columns):
                return ExportTable(sheet.title, row_number, columns)
    missing = ", ".join(sorted(REQUIRED_EXPORT_FIELDS))
    raise TemplateCompatibilityError(
        f"The official Excel export table is missing required columns: {missing}."
    )


def _first_empty_row(sheet, table: ExportTable) -> int:
    row_number = table.header_row + 1
    while row_number <= sheet.max_row:
        if all(sheet.cell(row_number, column).value in (None, "") for column in table.columns.values()):
            return row_number
        row_number += 1
    return sheet.max_row + 1


def _write_case_row(sheet, row_number: int, table: ExportTable, case: CaseRecord, lot: LotAllocation) -> None:
    values = {
        "source_id": case.source_id,
        "medical_record_number": case.medical_record_number,
        "patient_name": case.patient_name,
        "patient_id": case.patient_id,
        "birth_date": case.birth_date,
        "sex": case.sex,
        "report_date": case.report_date,
        "doctor_id": case.doctor_id,
        "official_material": case.official_material,
        "reason_code": case.reason_code,
        "reason_label": case.reason_label,
        "actual_quantity": case.actual_quantity,
        "lot_number": lot.lot_number,
        "lot_quantity": lot.quantity,
    }
    for field_name, column in table.columns.items():
        sheet.cell(row_number, column).value = values[field_name]


def _validate_generated_workbook(
    path: Path,
    table: ExportTable,
    cases: tuple[CaseRecord, ...],
    rows: list[int],
) -> None:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        loaded_table = find_export_table(workbook)
        if loaded_table.sheet_name != table.sheet_name or loaded_table.header_row != table.header_row:
            raise TemplateCompatibilityError("Generated workbook structure changed unexpectedly.")
        sheet = workbook[table.sheet_name]
        for row_number in rows:
            if not sheet.cell(row_number, table.columns["official_material"]).value:
                raise TemplateCompatibilityError("Generated workbook contains an empty medication row.")
        workbook.close()
    except TemplateCompatibilityError:
        raise
    except Exception as error:
        raise ExportError("Generated Excel validation failed.") from error


def _normalise_header(value: object) -> str:
    text = str(value or "").strip().casefold()
    return "".join(character for character in text if character.isalnum())

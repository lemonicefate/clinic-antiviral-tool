from datetime import date

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.cases import MISSING_REASON, READY_TO_EXPORT
from app.config import Settings
from app.database import Database
from app.his import InMemoryHisReader, Prescription
from app.main import create_app


def write_reason_template(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "OfficialCodes"
    sheet.append(["ReasonCode", "ReasonName"])
    sheet.append(["R01", "符合公費使用條件"])
    workbook.save(path)


def make_prescription(*, source_id="SOURCE-1", report_date=date(2026, 10, 9), doctor_id="D001"):
    return Prescription(
        source_id=source_id,
        medical_record_number="MRN001",
        patient_name="王小明",
        patient_id="P001",
        birth_date=date(1980, 1, 2),
        sex="M",
        report_date=report_date,
        doctor_id=doctor_id,
        medication_id="eraflu",
        medication_name="易剋冒膠囊",
        official_material="DDMTR2018090002:易剋冒膠囊(顆)",
        unit="capsule",
        source_quantity=10,
        treat="Y",
    )


def make_client(tmp_path, prescriptions):
    settings = Settings.for_testing(tmp_path)
    write_reason_template(settings.template_path)
    database = Database(settings.database_path)
    client = TestClient(
        create_app(settings=settings, his_reader=InMemoryHisReader(prescriptions), database=database)
    )
    return client, database


def test_selected_date_scan_creates_missing_case_once_and_shows_it_in_workbench(tmp_path):
    item = make_prescription()
    client, database = make_client(tmp_path, [item])

    first = client.post(
        "/pharmacy/scan",
        data={"scan_mode": "date", "scan_date": "2026-10-09", "operator": "P001"},
    )
    second = client.post(
        "/pharmacy/scan",
        data={"scan_mode": "date", "scan_date": "2026-10-09", "operator": "P001"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert database.count_cases() == 1
    assert database.get_case_by_source_id(item.source_id).state == MISSING_REASON
    assert item.patient_name in client.get("/pharmacy").text


def test_pharmacy_scan_rejects_range_longer_than_31_days(tmp_path):
    client, database = make_client(tmp_path, [make_prescription()])

    response = client.post(
        "/pharmacy/scan",
        data={
            "scan_mode": "range",
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "operator": "P001",
        },
    )

    assert response.status_code == 200
    assert "31 days or less" in response.text
    assert database.count_cases() == 0


def test_pharmacy_row_save_records_reason_quantity_lot_and_history(tmp_path):
    item = make_prescription()
    client, database = make_client(tmp_path, [item])
    client.post(
        "/pharmacy/scan",
        data={"scan_mode": "date", "scan_date": "2026-10-09", "operator": "P001"},
    )
    case = database.get_case_by_source_id(item.source_id)

    response = client.post(
        "/pharmacy/save",
        data={
            "case_id": str(case.id),
            "reason_code": "R01",
            "actual_quantity": "8",
            "lot_number": ["LOT-A"],
            "lot_quantity": ["8"],
            "operator": "P001",
        },
    )

    assert response.status_code == 200
    assert "Case saved." in response.text
    saved = database.get_case(case.id)
    assert saved.state == READY_TO_EXPORT
    assert [(lot.lot_number, lot.quantity) for lot in saved.lots] == [("LOT-A", 8)]
    assert {entry["field"] for entry in database.list_history(case.id)} == {
        "medication_use_reason",
        "actual_quantity",
        "lot_number",
    }


def test_exclude_and_reinclude_returns_case_to_its_derived_state(tmp_path):
    item = make_prescription()
    client, database = make_client(tmp_path, [item])
    client.post(
        "/pharmacy/scan",
        data={"scan_mode": "date", "scan_date": "2026-10-09", "operator": "P001"},
    )
    case = database.get_case_by_source_id(item.source_id)

    excluded = client.post(
        "/pharmacy/exclude",
        data={"case_id": str(case.id), "reason": "duplicate"},
    )
    assert excluded.status_code == 200
    assert "Case excluded." in excluded.text
    assert database.get_case(case.id).state == "excluded"

    reinclude = client.post("/pharmacy/reinclude", data={"case_id": str(case.id)})
    assert reinclude.status_code == 200
    assert "Case included again." in reinclude.text
    assert database.get_case(case.id).state == MISSING_REASON

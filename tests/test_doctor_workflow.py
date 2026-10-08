from datetime import date

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import Settings
from app.database import MISSING_LOT_QUANTITY, Database
from app.his import InMemoryHisReader, Prescription
from app.main import create_app


def write_reason_template(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "OfficialCodes"
    sheet.append(["ReasonCode", "ReasonName"])
    sheet.append(["R01", "符合公費使用條件"])
    sheet.append(["R02", "其他正式條件"])
    workbook.save(path)


def make_prescription():
    return Prescription(
        source_id="RELKEY-1|SYS-1|1",
        medical_record_number="MRN001",
        patient_name="王小明",
        patient_id="P001",
        birth_date=date(1980, 1, 2),
        sex="M",
        report_date=date(2026, 10, 9),
        doctor_id="D001",
        medication_id="eraflu",
        medication_name="易剋冒膠囊",
        official_material="DDMTR2018090002:易剋冒膠囊(顆)",
        unit="capsule",
        source_quantity=10,
        treat="Y",
    )


def test_doctor_save_creates_then_updates_one_case_and_clears_on_success(tmp_path):
    settings = Settings.for_testing(tmp_path)
    write_reason_template(settings.template_path)
    database = Database(settings.database_path)
    client = TestClient(create_app(settings=settings, his_reader=InMemoryHisReader([make_prescription()]), database=database))

    lookup = client.get("/doctor", params={"action": "recent", "doctor_id": "D001"})
    assert "R01 - 符合公費使用條件" in lookup.text

    saved = client.post(
        "/doctor/save",
        data={"source_id": "RELKEY-1|SYS-1|1", "reason_code": "R01", "doctor_id": "D001"},
    )
    assert saved.status_code == 200
    assert "已儲存用藥原因" in saved.text
    assert "王小明" not in saved.text
    assert database.count_cases() == 1
    assert database.get_case_by_source_id("RELKEY-1|SYS-1|1").state == MISSING_LOT_QUANTITY

    updated = client.post(
        "/doctor/save",
        data={"source_id": "RELKEY-1|SYS-1|1", "reason_code": "R02", "doctor_id": "D001"},
    )
    assert "已儲存用藥原因" in updated.text
    assert database.count_cases() == 1
    case = database.get_case_by_source_id("RELKEY-1|SYS-1|1")
    assert case.reason_code == "R02"
    assert case.reason_label == "其他正式條件"


def test_doctor_save_rejects_reason_outside_official_code_table_and_keeps_patient_on_screen(tmp_path):
    settings = Settings.for_testing(tmp_path)
    write_reason_template(settings.template_path)
    item = make_prescription()
    client = TestClient(create_app(settings=settings, his_reader=InMemoryHisReader([item])))

    response = client.post(
        "/doctor/save",
        data={"source_id": item.source_id, "reason_code": "NOT_OFFICIAL", "doctor_id": "D001"},
    )

    assert response.status_code == 200
    assert "Choose an official medication-use reason" in response.text
    assert item.patient_name in response.text


def test_doctor_reason_change_on_confirmed_case_requires_warning_then_returns_to_reporting(tmp_path):
    settings = Settings.for_testing(tmp_path)
    write_reason_template(settings.template_path)
    item = make_prescription()
    database = Database(settings.database_path)
    client = TestClient(create_app(settings=settings, his_reader=InMemoryHisReader([item]), database=database))
    case = database.save_doctor_reason(item, "R01", "符合公費使用條件", "D001")
    batch_id = database.create_export_batch("confirmed.xlsx", "P001", [case.id])
    database.mark_batch_uploaded(batch_id, str(tmp_path / "confirmed.xlsx"))
    database.confirm_cases([case.id])

    warning = client.post(
        "/doctor/save",
        data={"source_id": item.source_id, "reason_code": "R02", "doctor_id": "D001"},
    )
    assert "This case has already been confirmed in SMIS" in warning.text

    saved = client.post(
        "/doctor/save",
        data={
            "source_id": item.source_id,
            "reason_code": "R02",
            "doctor_id": "D001",
            "confirm_edit": "yes",
        },
    )
    assert "已儲存用藥原因" in saved.text
    assert database.get_case(case.id).reason_code == "R02"
    assert database.get_case(case.id).state == MISSING_LOT_QUANTITY


def test_mrn_search_requires_selection_when_multiple_orders_match(tmp_path):
    settings = Settings.for_testing(tmp_path)
    write_reason_template(settings.template_path)
    first = Prescription(**{**make_prescription().__dict__, "source_id": "ORDER-1"})
    second = Prescription(**{**make_prescription().__dict__, "source_id": "ORDER-2"})
    second = Prescription(**{**second.__dict__, "report_date": date(2026, 10, 8)})
    client = TestClient(
        create_app(settings=settings, his_reader=InMemoryHisReader([first, second]))
    )

    response = client.get("/doctor", params={"action": "mrn", "doctor_id": "D001", "mrn": "MRN001"})

    assert response.status_code == 200
    assert "請選擇處方" in response.text
    assert "ORDER-1" in response.text
    assert "ORDER-2" in response.text
    assert "No matching antiviral prescription" not in response.text

    selected = client.get(
        "/doctor",
        params={
            "action": "mrn",
            "doctor_id": "D001",
            "mrn": "MRN001",
            "source_id": "ORDER-2",
        },
    )

    assert "ORDER-2" in selected.text
    assert "用藥原因" in selected.text

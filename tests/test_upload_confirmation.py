from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.cases import LotAllocation, READY_TO_EXPORT
from app.config import Settings
from app.database import Database
from app.his import InMemoryHisReader, Prescription
from app.main import create_app


def write_template(path):
    workbook = Workbook()
    codes = workbook.active
    codes.title = "OfficialCodes"
    codes.append(["ReasonCode", "ReasonName"])
    codes.append(["R01", "符合公費使用條件"])
    report = workbook.create_sheet("Report")
    report.append(
        [
            "source_id", "medical_record_number", "patient_name", "patient_id", "birth_date", "sex",
            "report_date", "doctor_id", "official_material", "reason_code", "reason_label",
            "actual_quantity", "lot_number", "lot_quantity",
        ]
    )
    workbook.save(path)


def make_item():
    return Prescription(
        source_id="UPLOAD-1",
        medical_record_number="MRN-UPLOAD",
        patient_name="Patient Upload",
        patient_id="P-UPLOAD",
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


def setup_app(tmp_path):
    settings = Settings.for_testing(tmp_path)
    write_template(settings.template_path)
    database = Database(settings.database_path)
    item = make_item()
    client = TestClient(
        create_app(settings=settings, his_reader=InMemoryHisReader([item]), database=database)
    )
    case = database.ensure_case(item)
    database.save_pharmacy_fields(
        case.id,
        reason_code="R01",
        reason_label="符合公費使用條件",
        actual_quantity=10,
        lots=(LotAllocation("LOT-A", 10),),
        operator="P001",
    )
    return client, database, item


def generate_batch(client, database, item):
    case = database.get_case_by_source_id(item.source_id)
    response = client.post("/pharmacy/export", data={"export_case_ids": [str(case.id)], "operator": "P001"})
    assert "Exported: 1" in response.text
    return database.get_export_batch(1), case


def test_uploaded_batch_preserves_workbook_and_marks_cases_uploaded(tmp_path):
    client, database, item = setup_app(tmp_path)
    batch, case = generate_batch(client, database, item)
    source_path = tmp_path / "app-data" / "exports" / batch["filename"]
    source_bytes = source_path.read_bytes()

    response = client.post("/pharmacy/batch/1/uploaded")

    assert response.status_code == 200
    assert "preserved" in response.text
    uploaded = database.get_export_batch(1)
    preserved_path = Path(uploaded["preserved_path"])
    assert uploaded["uploaded"] == 1
    assert preserved_path.exists()
    assert preserved_path.read_bytes() == source_bytes
    assert database.get_case(case.id).state == "uploaded"


def test_uploaded_cases_can_be_confirmed_and_default_view_hides_confirmed(tmp_path):
    client, database, item = setup_app(tmp_path)
    _, case = generate_batch(client, database, item)
    client.post("/pharmacy/batch/1/uploaded")

    confirmed = client.post("/pharmacy/confirm", data={"confirm_case_ids": [str(case.id)]})

    assert confirmed.status_code == 200
    assert "Cases marked confirmed" in confirmed.text
    assert database.get_case(case.id).state == "confirmed"
    assert item.patient_name not in client.get("/pharmacy").text
    assert item.patient_name in client.get("/pharmacy?view=all").text


def test_manually_reselecting_uploaded_case_shows_export_warning(tmp_path):
    client, database, item = setup_app(tmp_path)
    _, case = generate_batch(client, database, item)
    client.post("/pharmacy/batch/1/uploaded")

    response = client.post("/pharmacy/export", data={"export_case_ids": [str(case.id)], "operator": "P001"})

    assert "already uploaded" in response.text


def test_editing_confirmed_case_warns_then_returns_it_to_reporting_flow(tmp_path):
    client, database, item = setup_app(tmp_path)
    _, case = generate_batch(client, database, item)
    client.post("/pharmacy/batch/1/uploaded")
    client.post("/pharmacy/confirm", data={"confirm_case_ids": [str(case.id)]})

    warning = client.post(
        "/pharmacy/save",
        data={
            "case_id": str(case.id),
            "reason_code": "R01",
            "actual_quantity": "8",
            "lot_number": ["LOT-C"],
            "lot_quantity": ["8"],
            "operator": "P001",
        },
    )
    assert "This case has already been confirmed in SMIS" in warning.text

    saved = client.post(
        "/pharmacy/save",
        data={
            "case_id": str(case.id),
            "reason_code": "R01",
            "actual_quantity": "8",
            "lot_number": ["LOT-C"],
            "lot_quantity": ["8"],
            "operator": "P001",
            "confirm_edit": "yes",
        },
    )

    assert "Case saved." in saved.text
    assert database.get_case(case.id).state == READY_TO_EXPORT

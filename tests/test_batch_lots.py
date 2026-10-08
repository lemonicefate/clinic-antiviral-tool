from datetime import date

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.cases import MISSING_REASON
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


def make_prescription(source_id, medication_id="eraflu"):
    return Prescription(
        source_id=source_id,
        medical_record_number=source_id,
        patient_name=f"Patient {source_id}",
        patient_id=source_id,
        birth_date=date(1980, 1, 2),
        sex="M",
        report_date=date(2026, 10, 9),
        doctor_id="D001",
        medication_id=medication_id,
        medication_name="易剋冒膠囊" if medication_id == "eraflu" else "Other antiviral",
        official_material="DDMTR2018090002:易剋冒膠囊(顆)" if medication_id == "eraflu" else "OTHER",
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
    client.post(
        "/pharmacy/scan",
        data={"scan_mode": "date", "scan_date": "2026-10-09", "operator": "P001"},
    )
    return client, database


def test_batch_lot_applies_full_actual_quantity_to_same_medication_cases(tmp_path):
    client, database = make_client(tmp_path, [make_prescription("A"), make_prescription("B")])
    cases = database.list_cases()

    response = client.post(
        "/pharmacy/batch-lot",
        data={
            "case_ids": [str(case.id) for case in cases],
            "lot_number": "LOT-SAME",
            "operator": "P001",
        },
    )

    assert response.status_code == 200
    assert "Batch lot applied." in response.text
    assert all(case.lots[0].lot_number == "LOT-SAME" for case in database.list_cases())
    assert all(case.lots[0].quantity == case.actual_quantity for case in database.list_cases())


def test_batch_lot_rejects_mixed_medications_without_changing_cases(tmp_path):
    client, database = make_client(
        tmp_path,
        [make_prescription("A"), make_prescription("B", medication_id="other")],
    )
    cases = database.list_cases()

    response = client.post(
        "/pharmacy/batch-lot",
        data={
            "case_ids": [str(case.id) for case in cases],
            "lot_number": "LOT-MIXED",
            "operator": "P001",
        },
    )

    assert response.status_code == 200
    assert "Separate medications" in response.text
    assert all(not case.lots for case in database.list_cases())
    assert all(case.state == MISSING_REASON for case in database.list_cases())


def test_workbench_exposes_additional_lot_action(tmp_path):
    client, _ = make_client(tmp_path, [make_prescription("A")])

    assert "+ Add another lot" in client.get("/pharmacy").text

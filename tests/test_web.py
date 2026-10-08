from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.his import InMemoryHisReader, Prescription
from app.main import create_app


def test_doctor_page_displays_patient_identity_for_recent_prescription(tmp_path):
    item = Prescription(
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
    settings = Settings.for_testing(tmp_path)
    client = TestClient(create_app(settings=settings, his_reader=InMemoryHisReader([item])))

    response = client.get("/doctor", params={"action": "recent", "doctor_id": "D001"})

    assert response.status_code == 200
    assert "王小明" in response.text
    assert "MRN001" in response.text
    assert "易剋冒膠囊" in response.text
    assert "10 capsule" in response.text

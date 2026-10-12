from datetime import date, time

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
        report_date=date.today(),
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
    assert 'class="panel index-panel"' in response.text
    assert 'id="today-index-success"' in response.text


def test_doctor_index_status_is_visible_and_recent_candidates_can_be_selected(tmp_path):
    today = date.today()
    first = Prescription(
        source_id="RELKEY-1|SYS-1|1",
        medical_record_number="MRN001",
        patient_name="王小明",
        patient_id="P001",
        birth_date=date(1980, 1, 2),
        sex="M",
        report_date=today,
        doctor_id="D001",
        medication_id="eraflu",
        medication_name="易剋冒膠囊",
        official_material="DDMTR2018090002:易剋冒膠囊(顆)",
        unit="capsule",
        source_quantity=8,
        treat="Y",
        report_time=time(9, 0),
    )
    second = Prescription(**{**first.__dict__, "source_id": "RELKEY-2|SYS-2|2", "report_time": time(9, 5)})
    settings = Settings.for_testing(tmp_path)
    client = TestClient(create_app(settings=settings, his_reader=InMemoryHisReader([first, second])))

    status = client.get("/doctor/index-status")
    assert status.status_code == 200
    assert status.json()["state"] == "ready"

    response = client.get("/doctor", params={"action": "recent", "doctor_id": "D001"})
    assert "今日找到多筆抗病毒處方" in response.text
    assert "RELKEY-2|SYS-2|2" in response.text

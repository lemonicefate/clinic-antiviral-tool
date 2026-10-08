from datetime import date, timedelta

import pytest

from app.his import DateRangeError, InMemoryHisReader, Prescription


def prescription(
    source_id: str,
    *,
    doctor_id: str = "D001",
    mrn: str = "MRN001",
    report_date: date = date(2026, 10, 9),
    patient_name: str = "王小明",
) -> Prescription:
    return Prescription(
        source_id=source_id,
        medical_record_number=mrn,
        patient_name=patient_name,
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


def test_recent_and_mrn_queries_return_normalized_prescriptions():
    reader = InMemoryHisReader(
        [
            prescription("old", report_date=date(2026, 10, 8)),
            prescription("new", report_date=date(2026, 10, 9)),
            prescription("other-doctor", doctor_id="D002", report_date=date(2026, 10, 7)),
        ]
    )

    assert reader.most_recent("D001").source_id == "new"
    assert [item.source_id for item in reader.find_by_mrn("MRN001")] == [
        "new",
        "old",
        "other-doctor",
    ]


def test_scan_rejects_ranges_longer_than_31_calendar_days():
    reader = InMemoryHisReader([prescription("one")])

    with pytest.raises(DateRangeError) as error:
        reader.scan(date(2026, 1, 1), date(2026, 2, 1))

    assert error.value.code == "HIS_RANGE_001"


def test_scan_accepts_a_31_day_inclusive_range_and_rereads_by_source_identity():
    item = prescription("known", report_date=date(2026, 1, 31))
    reader = InMemoryHisReader([item])

    assert reader.scan(date(2026, 1, 1), date(2026, 1, 31)) == [item]
    assert reader.get("known") == item
    assert reader.get("missing") is None

from datetime import date, time, timedelta
from pathlib import Path

import pytest

from app.his import DateRangeError, DbfHisReader, HisReadError, InMemoryHisReader, Prescription


def prescription(
    source_id: str,
    *,
    doctor_id: str = "D001",
    mrn: str = "MRN001",
    report_date: date = date(2026, 10, 9),
    patient_name: str = "王小明",
    report_time: time | None = None,
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
        report_time=report_time,
    )


def test_recent_and_mrn_queries_return_normalized_prescriptions():
    today = date(2026, 10, 11)
    reader = InMemoryHisReader(
        [
            prescription("old", report_date=date(2026, 10, 10)),
            prescription("new", report_date=today),
            prescription("other-doctor", doctor_id="D002", report_date=date(2026, 10, 7)),
        ],
        today_provider=lambda: today,
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


def test_recent_candidates_use_his_time_and_limit_optional_recent_window():
    today = date(2026, 10, 11)
    reader = InMemoryHisReader(
        [
            prescription("older", report_date=today, report_time=time(9, 0)),
            prescription("newer", report_date=today, report_time=time(9, 5)),
            prescription("unknown-time", report_date=today),
            prescription("yesterday", report_date=date(2026, 10, 10), report_time=time(23, 59)),
        ],
        today_provider=lambda: today,
    )

    assert [item.source_id for item in reader.recent_candidates("D001")] == [
        "newer",
        "older",
        "unknown-time",
    ]
    assert [item.source_id for item in reader.recent_candidates("D001", start_time=time(9, 1))] == [
        "newer",
    ]


def test_synchronous_index_build_reports_his_error_instead_of_false_no_match():
    reader = DbfHisReader(None, today_provider=lambda: date(2026, 10, 11))

    with pytest.raises(HisReadError) as error:
        reader.most_recent("D001")

    assert error.value.code == "HIS_READ_001"


def test_today_index_status_exposes_phase_counts_and_progress_mode():
    reader = DbfHisReader(None, today_provider=lambda: date(2026, 10, 11))

    reader._set_index_status(
        "building",
        42,
        "正在配對抗病毒處方",
        phase="items",
        processed=420,
        total=1000,
        progress_mode="determinate",
    )

    status = reader.index_status()
    assert status["state"] == "building"
    assert status["progress"] == 42
    assert status["phase"] == "items"
    assert status["processed"] == 420
    assert status["total"] == 1000
    assert status["progress_mode"] == "determinate"
    assert status["updated_at"]


def test_dbf_reader_uses_ch011m1_doc_as_doctor_id():
    class StubDbfReader(DbfHisReader):
        def __init__(self, tables):
            super().__init__(
                mirror_path=Path("."),
                today_provider=lambda: date(2026, 10, 11),
            )
            self.tables = tables

        def _read_table(self, table_name, *, required=True):
            return self.tables.get(table_name, [])

    reader = StubDbfReader(
        {
            "CH012M1": [
                {
                    "RELKEY": "REL-1",
                    "SYS_2015": "SYS-1",
                    "MED1": "ERA",
                    "ITEMN": "ERA",
                    "ITEMSEQ": "1",
                    "USE_TAMT": "10",
                    "TREAT": "Y",
                }
            ],
            "CH011M1": [
                {
                    "RELKEY": "REL-1",
                    "SYS_2015": "SYS-1",
                    "SDATE": date(2026, 10, 11),
                    "DOC": "0307",
                    "ID": "A123456789",
                    "NUM": "000001",
                }
            ],
            "PD011M1": [
                {
                    "ID": "A123456789",
                    "NUM": "000001",
                    "NAME": "王小明",
                    "BIRTH": date(1980, 1, 2),
                    "SEX": "M",
                }
            ],
            "H_INV": [{"ITEMN": "ERA", "LABNUM": "A059653100"}],
        }
    )

    result = reader._all_prescriptions()

    assert len(result) == 1
    assert result[0].doctor_id == "0307"
    assert result[0].medical_record_number == "000001"
    assert result[0].patient_name == "王小明"
    assert result[0].patient_id == "A123456789"
    assert result[0].birth_date == date(1980, 1, 2)
    assert result[0].sex == "M"


def test_dbf_reader_reuses_unchanged_snapshot_for_repeated_recent_lookup():
    class CountingDbfReader(DbfHisReader):
        def __init__(self, tables):
            super().__init__(
                mirror_path=Path("."),
                today_provider=lambda: date(2026, 10, 11),
            )
            self.tables = tables
            self.read_calls = []

        def _iter_table(self, table_name, *, required=True):
            self.read_calls.append(table_name)
            yield from self.tables.get(table_name, [])

    tables = {
        "CH012M1": [
            {
                "RELKEY": "REL-1",
                "SYS_2015": "SYS-1",
                "MED1": "ERA",
                "ITEMN": "ERA",
                "USE_TAMT": "10",
                "TREAT": "Y",
            }
        ],
        "CH011M1": [
            {
                "RELKEY": "REL-1",
                "SYS_2015": "",
                "SDATE": date(2026, 10, 11),
                "DOC": "0307",
                "ID": "A123456789",
                "NUM": "000001",
            }
        ],
        "PD011M1": [
            {
                "ID": "A123456789",
                "NUM": "000001",
                "NAME": "王小明",
                "BIRTH": date(1980, 1, 2),
                "SEX": "M",
            }
        ],
    }
    reader = CountingDbfReader(tables)

    assert reader.most_recent("0307").patient_name == "王小明"
    assert reader.most_recent("0307").patient_name == "王小明"

    assert set(reader.read_calls) == {"CH012M1", "CH011M1", "PD011M1"}
    assert len(reader.read_calls) == 3


def test_dbf_reader_recent_lookup_is_limited_to_today():
    class StreamingStubDbfReader(DbfHisReader):
        def __init__(self, tables):
            super().__init__(
                mirror_path=Path("."),
                today_provider=lambda: date(2026, 10, 11),
            )
            self.tables = tables
            self.iterated_tables = []

        def _iter_table(self, table_name, *, required=True):
            self.iterated_tables.append(table_name)
            yield from self.tables.get(table_name, [])

    def item(source_id, relkey):
        return {
            "RELKEY": relkey,
            "SYS_2015": "SYS-1",
            "MED1": "ERA",
            "ITEMN": "ERA",
            "ITEMSEQ": source_id,
            "USE_TAMT": "8",
            "TREAT": "Y",
        }

    reader = StreamingStubDbfReader(
        {
            "CH011M1": [
                {
                    "RELKEY": "OLD-1",
                    "SYS_2015": "SYS-1",
                    "SDATE": date(2026, 10, 10),
                    "DOC": "0307",
                    "ID": "A123456789",
                    "NUM": "000001",
                },
                {
                    "RELKEY": "TODAY-1",
                    "SYS_2015": "SYS-1",
                    "SDATE": date(2026, 10, 11),
                    "DOC": "0307",
                    "ID": "A123456789",
                    "NUM": "000001",
                },
            ],
            "CH012M1": [item("old", "OLD-1"), item("today", "TODAY-1")],
            "PD011M1": [
                {
                    "ID": "A123456789",
                    "NUM": "000001",
                    "NAME": "王小明",
                    "BIRTH": date(1980, 1, 2),
                    "SEX": "M",
                }
            ],
        }
    )

    result = reader.most_recent("0307")

    assert result is not None
    assert result.source_id == "TODAY-1|SYS-1|today|ERA"
    assert reader.iterated_tables == ["CH011M1", "CH012M1", "PD011M1"]


def test_dbf_reader_recent_lookup_does_not_fall_back_to_previous_date():
    class StreamingStubDbfReader(DbfHisReader):
        def __init__(self):
            super().__init__(
                mirror_path=Path("."),
                today_provider=lambda: date(2026, 10, 11),
            )

        def _iter_table(self, table_name, *, required=True):
            if table_name == "CH011M1":
                yield {
                    "RELKEY": "OLD-1",
                    "SYS_2015": "SYS-1",
                    "SDATE": date(2026, 10, 10),
                    "DOC": "0307",
                    "ID": "A123456789",
                    "NUM": "000001",
                }
            elif table_name == "CH012M1":
                yield {
                    "RELKEY": "OLD-1",
                    "SYS_2015": "SYS-1",
                    "MED1": "ERA",
                    "ITEMN": "ERA",
                    "ITEMSEQ": "old",
                    "USE_TAMT": "8",
                    "TREAT": "Y",
                }
            elif table_name == "PD011M1":
                yield {
                    "ID": "A123456789",
                    "NUM": "000001",
                    "NAME": "王小明",
                    "BIRTH": date(1980, 1, 2),
                    "SEX": "M",
                }

    assert StreamingStubDbfReader().most_recent("0307") is None


def test_dbf_reader_get_rereads_the_selected_order():
    class StreamingStubDbfReader(DbfHisReader):
        def __init__(self, tables):
            super().__init__(mirror_path=Path("."))
            self.tables = tables
            self.iterated_tables = []

        def _iter_table(self, table_name, *, required=True):
            self.iterated_tables.append(table_name)
            yield from self.tables.get(table_name, [])

    tables = {
        "CH012M1": [
            {
                "RELKEY": "REL-1",
                "SYS_2015": "SYS-1",
                "MED1": "ERA",
                "ITEMN": "ERA",
                "ITEMSEQ": "1",
                "USE_TAMT": "8",
                "TREAT": "Y",
            }
        ],
        "CH011M1": [
            {
                "RELKEY": "REL-1",
                "SYS_2015": "SYS-1",
                "SDATE": date(2026, 10, 11),
                "DOC": "0307",
                "ID": "A123456789",
                "NUM": "000001",
            }
        ],
        "PD011M1": [
            {
                "ID": "A123456789",
                "NUM": "000001",
                "NAME": "王小明",
            }
        ],
    }
    reader = StreamingStubDbfReader(tables)
    source_id = "REL-1|SYS-1|1|ERA"

    first = reader.get(source_id)
    tables["CH012M1"][0]["USE_TAMT"] = "12"
    second = reader.get(source_id)

    assert first is not None
    assert first.source_quantity == 8
    assert second is not None
    assert second.source_quantity == 12
    assert reader.iterated_tables == [
        "CH012M1",
        "CH011M1",
        "PD011M1",
        "CH012M1",
        "CH011M1",
        "PD011M1",
    ]

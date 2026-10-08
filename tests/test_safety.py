from app.safety import find_sensitive_paths


def test_patient_data_guard_detects_all_required_file_variants():
    paths = [
        "copy.dbf",
        "COPY.DBF",
        "memo.fpt",
        "memo.FPT",
        "index.cdx",
        "index.CDX",
        ".env",
        "README.md",
    ]

    assert find_sensitive_paths(paths) == paths[:-1]

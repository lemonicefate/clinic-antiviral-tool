import subprocess

from app.safety import find_sensitive_paths
from app.safety import tracked_sensitive_paths


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


def test_git_guard_detects_a_staged_dbf_file(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    (tmp_path / "patient.DBF").write_bytes(b"")
    subprocess.run(["git", "-C", str(tmp_path), "add", "patient.DBF"], check=True)

    assert tracked_sensitive_paths(tmp_path) == ["patient.DBF"]

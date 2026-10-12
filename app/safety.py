from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable


SENSITIVE_SUFFIXES = {".dbf", ".fpt", ".cdx"}


def find_sensitive_paths(paths: Iterable[str]) -> list[str]:
    offenders: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.name.lower() == ".env" or path.suffix.lower() in SENSITIVE_SUFFIXES:
            offenders.append(raw_path)
    return offenders


def tracked_sensitive_paths(repository: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repository), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    paths = [path for path in result.stdout.decode("utf-8").split("\0") if path]
    return find_sensitive_paths(paths)

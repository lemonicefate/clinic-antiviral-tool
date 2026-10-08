from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.safety import tracked_sensitive_paths


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    offenders = tracked_sensitive_paths(repository)
    if offenders:
        print("Sensitive HIS or environment files are tracked/staged:")
        print("\n".join(f"- {path}" for path in offenders))
        return 1
    print("Patient-data Git guard passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

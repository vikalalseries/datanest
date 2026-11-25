"""Check a backend env file against the production safety rules BEFORE you deploy.

    python scripts/check_env.py backend/.env            # shows what would stop the app starting in production
    python scripts/check_env.py path/to/prod.env

It never prints secret values, only which rule failed. Exit code 1 if there are blocking problems.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings, production_problems  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"not found: {path}")
        return 2
    s = Settings(_env_file=str(path), env="production")  # evaluate as if ENV=production, whatever the file says
    errors, warnings = production_problems(s)
    print(f"Checking {path} as a PRODUCTION config\n")
    for e in errors:
        print(f"  [BLOCKING] {e}")
    for w in warnings:
        print(f"  [warning]  {w}")
    if not errors and not warnings:
        print("  all good")
    print(f"\n{len(errors)} blocking problem(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

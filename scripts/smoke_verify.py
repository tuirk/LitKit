#!/usr/bin/env python3
"""Quick LitKit pipeline smoke check using projects/_demo/."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "_demo"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--max-records", type=int, default=10)
    args = ap.parse_args()

    py = sys.executable
    project_dir = ROOT / "projects" / args.project
    if not project_dir.exists():
        print(f"Demo project missing: {project_dir}", file=sys.stderr)
        return 1

    db = project_dir / "project.db"
    if not db.exists():
        run([py, "scripts/00_init_project.py", "--project", args.project])

    run([py, "scripts/02_search_open.py", "--project", args.project, "--max-records", str(args.max_records)])
    run([py, "scripts/03_dedup.py", "--project", args.project])
    run([py, "scripts/05_resolve_oa.py", "--project", args.project])
    run([py, "scripts/09_export.py", "--project", args.project])
    print("Smoke verify OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Commit a full-text screening batch.

Mirror of 04b_screen_commit but for pass='full_text'.

Usage:
  python scripts/07b_fulltext_commit.py --batch projects/<id>/screening/ft_batch_001.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import connect, log_event


VALID_DECISIONS = {"include", "exclude", "unsure"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--decided-by", default="agent",
                    help="'agent' or 'human' or 'llm:<provider>'")
    args = ap.parse_args()

    batch_path = Path(args.batch).resolve()
    if not batch_path.exists():
        print(f"Not found: {batch_path}")
        sys.exit(1)

    project_dir = batch_path.parent.parent
    db_path = project_dir / "project.db"
    if not db_path.exists():
        print(f"No project.db at {db_path}")
        sys.exit(1)

    rows = []
    with open(batch_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[error] line {lineno}: invalid JSON ({e})")
                sys.exit(1)
            for key in ("record_id", "decision"):
                if key not in obj:
                    print(f"[error] line {lineno}: missing '{key}'")
                    sys.exit(1)
            if obj["decision"] not in VALID_DECISIONS:
                print(f"[error] line {lineno}: decision='{obj['decision']}' "
                      f"not in {VALID_DECISIONS}")
                sys.exit(1)
            rows.append(obj)

    counts = {"include": 0, "exclude": 0, "unsure": 0}
    with connect(db_path) as conn:
        for obj in rows:
            counts[obj["decision"]] += 1
            conn.execute(
                "INSERT OR REPLACE INTO screening "
                "(record_id, pass, decision, reason, criteria_hit, "
                " decided_by, batch_id) "
                "VALUES (?,'full_text',?,?,?,?,?)",
                (obj["record_id"], obj["decision"], obj.get("reason"),
                 json.dumps(obj.get("criteria_hit") or []),
                 args.decided_by, obj.get("batch_id"))
            )
        log_event(conn, "screen", "info",
                  f"Committed full-text batch {batch_path.name}",
                  {"counts": counts, "decided_by": args.decided_by})

    print(f"Committed (full-text): {len(rows)} records from {batch_path.name}")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print()
    print("Next: python scripts/08_snowball.py --project <id>")
    print("  (or 09_export.py if you're done)")


if __name__ == "__main__":
    main()

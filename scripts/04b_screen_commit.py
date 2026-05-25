#!/usr/bin/env python3
"""Validate and commit a screening batch.

Reads a JSONL the agent has labeled, validates schema, writes labels to DB.

Usage:
  python scripts/04b_screen_commit.py --batch projects/<id>/screening/batch_001.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.store import connect, log_event


VALID_DECISIONS = {"include", "exclude", "unsure"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="Path to batch JSONL")
    ap.add_argument("--pass-name", default="title_abstract")
    ap.add_argument("--decided-by", default="agent",
                    help="'agent' or 'human'")
    args = ap.parse_args()

    batch_path = Path(args.batch).resolve()
    if not batch_path.exists():
        print(f"Not found: {batch_path}")
        sys.exit(1)

    # The DB lives at projects/<id>/project.db. Walk up from screening/.
    project_dir = batch_path.parent.parent
    db_path = project_dir / "project.db"
    if not db_path.exists():
        print(f"No project.db at {db_path}")
        sys.exit(1)

    # Validate first
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
    auto_seed_count = 0
    with connect(db_path) as conn:
        for obj in rows:
            counts[obj["decision"]] += 1
            conn.execute(
                "INSERT OR REPLACE INTO screening "
                "(record_id, pass, decision, reason, criteria_hit, decided_by, batch_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (obj["record_id"], args.pass_name, obj["decision"],
                 obj.get("reason"),
                 json.dumps(obj.get("criteria_hit") or []),
                 args.decided_by, obj.get("batch_id"))
            )
        if args.pass_name == "title_abstract":
            seed_rows = conn.execute(
                """
                SELECT r.id
                FROM records r
                LEFT JOIN screening s
                  ON s.record_id = r.id
                 AND s.pass = 'title_abstract'
                WHERE COALESCE(r.from_seed, 0) = 1
                  AND s.id IS NULL
                """
            ).fetchall()
            for r in seed_rows:
                conn.execute(
                    "INSERT INTO screening "
                    "(record_id, pass, decision, reason, criteria_hit, decided_by, batch_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        r["id"], "title_abstract", "include",
                        "Auto-included as scoping seed; spot-check that this paper fits the inclusion criteria as written.",
                        json.dumps([]), "seed", "seed_auto_include",
                    ),
                )
            auto_seed_count = len(seed_rows)
        log_event(conn, "screen", "info",
                  f"Committed batch {batch_path.name}",
                  {"counts": counts, "decided_by": args.decided_by,
                   "auto_included_seeds": auto_seed_count})

    print(f"Committed: {len(rows)} records from {batch_path.name}")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if auto_seed_count:
        print()
        print(f"Auto-included {auto_seed_count} scoping seed(s) at title/abstract screening.")
        print("Spot-check that each seed fits the inclusion/exclusion criteria as written.")
    print()
    print("Next: another batch with python scripts/04_screen_prep.py --project ...")
    print("      or python scripts/05_resolve_oa.py --project ... once screening is done")


if __name__ == "__main__":
    main()

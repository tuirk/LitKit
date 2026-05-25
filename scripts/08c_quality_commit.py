#!/usr/bin/env python3
"""Commit an agent-authored risk-of-bias batch.

Usage:
  python scripts/08c_quality_commit.py --batch projects/<id>/screening/quality_batch_001.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.store import connect, log_event

VALID_ROB = {"low", "some_concerns", "high", "unclear"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--extracted-by", default="agent:risk_of_bias",
                    help="Audit label for the extraction writer")
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
            if "record_id" not in obj:
                print(f"[error] line {lineno}: missing 'record_id'")
                sys.exit(1)
            quality = obj.get("quality") or {}
            rob = quality.get("risk_of_bias_overall")
            if rob not in VALID_ROB:
                print(f"[error] line {lineno}: risk_of_bias_overall must be one of {sorted(VALID_ROB)}")
                sys.exit(1)
            if not quality.get("risk_of_bias_notes"):
                print(f"[error] line {lineno}: missing risk_of_bias_notes")
                sys.exit(1)
            rows.append(obj)

    with connect(db_path) as conn:
        for obj in rows:
            quality = obj.get("quality") or {}
            fields = obj.get("fields") or {}
            chars_seen = len(obj.get("fulltext_excerpt") or "")
            conn.execute(
                "INSERT OR REPLACE INTO extractions "
                "(record_id, fields_json, methodological_rigor, "
                " evidence_strength, limitations_acknowledged, quality_notes, "
                " risk_of_bias_tool, risk_of_bias_overall, "
                " risk_of_bias_domains_json, risk_of_bias_notes, "
                " extracted_by, source_text_chars) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    obj["record_id"],
                    json.dumps(fields),
                    quality.get("methodological_rigor"),
                    quality.get("evidence_strength"),
                    quality.get("limitations_acknowledged"),
                    quality.get("quality_notes"),
                    quality.get("risk_of_bias_tool"),
                    quality.get("risk_of_bias_overall"),
                    json.dumps(quality.get("risk_of_bias_domains") or []),
                    quality.get("risk_of_bias_notes"),
                    args.extracted_by,
                    chars_seen,
                ),
            )
        log_event(
            conn, "extract", "info",
            f"Committed risk-of-bias batch {batch_path.name}",
            {"count": len(rows), "extracted_by": args.extracted_by}
        )

    print(f"Committed risk-of-bias batch: {batch_path.name}")
    print(f"  records: {len(rows)}")
    print(f"  extracted_by: {args.extracted_by}")
    print()
    print("Risk-of-bias data is now available in the extractions table for export.")


if __name__ == "__main__":
    main()

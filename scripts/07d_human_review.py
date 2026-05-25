#!/usr/bin/env python3
"""Human review of LLM recommendations from 07c.

Two operations:

  --print-summary
      Print a numbered summary table of all records grouped by recommendation
      (includes / excludes / unsures). The agent uses this to ask the user
      two questions: which includes to override out, which excludes/unsures
      to flip in.

  --commit
      Read the review file (after the user has filled in `your_decision`
      for the records they want to override) and write final
      `decided_by='human'` decisions to the screening table for ALL
      records — overrides AND unchanged-from-LLM.

Typical agent flow:
  1. python 07d_human_review.py --review <path> --print-summary
  2. agent shows the summary, asks user 2 questions
  3. agent edits the JSONL: sets your_decision/your_reason on records the
     user wants to override; copies LLM recommendation onto the rest
  4. python 07d_human_review.py --review <path> --commit
"""
import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # Windows consoles may default to a legacy codepage; avoid crashing on Unicode titles.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.store import connect, log_event


VALID_DECISIONS = {"include", "exclude", "unsure"}


def cmd_print_summary(review_path: Path) -> None:
    by_decision = {"include": [], "exclude": [], "unsure": []}
    with open(review_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            d = obj["llm_recommendation"]["decision"]
            by_decision.setdefault(d, []).append(obj)

    total = sum(len(v) for v in by_decision.values())
    print(f"# LLM full-text review summary — {total} records\n")
    print(f"  include: {len(by_decision['include'])}")
    print(f"  exclude: {len(by_decision['exclude'])}")
    print(f"  unsure:  {len(by_decision['unsure'])}\n")

    for label in ("include", "exclude", "unsure"):
        rows = by_decision[label]
        if not rows:
            continue
        print(f"## LLM-recommended {label.upper()} ({len(rows)})\n")
        for i, r in enumerate(rows, 1):
            short = (r.get("title") or "(no title)")[:80]
            year = r.get("year") or "—"
            reason = r["llm_recommendation"].get("reason", "")
            print(f"{i:3d}. {r['canonical_id']} ({year}) {short}")
            print(f"     why: {reason}")
            q = r.get("quality") or {}
            if q:
                rig = q.get("methodological_rigor") or "?"
                ev = q.get("evidence_strength") or "?"
                qn = q.get("quality_notes") or ""
                print(f"     quality: rigor={rig} evidence={ev} — {qn[:80]}")
            print()


def cmd_commit(review_path: Path) -> None:
    project_dir = review_path.parent.parent
    db_path = project_dir / "project.db"
    if not db_path.exists():
        print(f"No project.db at {db_path}")
        sys.exit(1)

    rows = []
    with open(review_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            # If the user (via the agent) didn't set your_decision, copy the
            # LLM recommendation. The decision still gets recorded as
            # decided_by='human' because the human implicitly accepted it.
            if obj.get("your_decision") is None:
                obj["your_decision"] = obj["llm_recommendation"]["decision"]
                obj["your_reason"] = (
                    obj.get("your_reason")
                    or f"[accepted LLM recommendation] "
                       f"{obj['llm_recommendation'].get('reason', '')}"
                )
                obj["criteria_hit"] = obj.get("criteria_hit") or \
                    obj["llm_recommendation"].get("criteria_hit", [])
            if obj["your_decision"] not in VALID_DECISIONS:
                print(f"[error] line {lineno}: your_decision='{obj['your_decision']}' "
                      f"not in {VALID_DECISIONS}")
                sys.exit(1)
            rows.append(obj)

    overrides = sum(
        1 for r in rows
        if r["your_decision"] != r["llm_recommendation"]["decision"]
    )

    counts = {"include": 0, "exclude": 0, "unsure": 0}
    with connect(db_path) as conn:
        for r in rows:
            counts[r["your_decision"]] += 1
            conn.execute(
                "INSERT OR REPLACE INTO screening "
                "(record_id, pass, decision, reason, criteria_hit, "
                " decided_by, batch_id) "
                "VALUES (?,'full_text',?,?,?,'human',?)",
                (
                    r["record_id"],
                    r["your_decision"],
                    r.get("your_reason") or "",
                    json.dumps(r.get("criteria_hit") or []),
                    review_path.stem,
                ),
            )
        log_event(conn, "screen", "info",
                  f"Human full-text review committed: {review_path.name}",
                  {"counts": counts, "total": len(rows),
                   "overrides_vs_llm": overrides})

    print(f"Committed {len(rows)} human full-text decisions.")
    print(f"  include: {counts['include']}")
    print(f"  exclude: {counts['exclude']}")
    print(f"  unsure:  {counts['unsure']}")
    print(f"  overrides vs LLM: {overrides}")
    print()
    print("Next: 08_snowball.py (optional) or 09_export.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True,
                    help="Path to ft_review_NNN.jsonl from 07c_llm_fulltext")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--print-summary", action="store_true",
                   help="Print numbered summary grouped by LLM recommendation")
    g.add_argument("--commit", action="store_true",
                   help="Commit decisions in the review file as decided_by='human'")
    args = ap.parse_args()

    review_path = Path(args.review).resolve()
    if not review_path.exists():
        print(f"Not found: {review_path}")
        sys.exit(1)

    if args.print_summary:
        cmd_print_summary(review_path)
    elif args.commit:
        cmd_commit(review_path)


if __name__ == "__main__":
    main()

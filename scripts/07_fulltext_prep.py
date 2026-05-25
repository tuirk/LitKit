#!/usr/bin/env python3
"""Prepare a full-text screening batch.

After title/abstract screening included some records, downloads fetched
full text for the OA-eligible ones, you do a second-pass screen on the
actual paper. This script writes a batch JSONL with extracted full text
(or PDF paths for the agent to open).

The Markdown normalization step also extracts an introduction/conclusion
excerpt. That supports an optional triage round between abstract screening
and full-text reading:
  - if the batch is larger than 100 records, do an intro/conclusion pass
    before the full read
  - if the batch is 100 records or fewer, ask the user whether they want
    that intro/conclusion pass first

Only records with:
  - title_abstract decision = 'include'
  - downloads.status = 'success'
are included. Records that were title-included but couldn't be downloaded
get listed in a separate `not_downloaded.txt` for ILL/manual handling.

Usage:
  python scripts/07_fulltext_prep.py --project <id>
  python scripts/07_fulltext_prep.py --project <id> --batch-size 5
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.fulltext_markdown import convert_to_markdown
from litkit.store import ProjectConfig, ProjectPaths, connect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument("--max-text-chars", type=int, default=30000)
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()
    if args.batch_size > 5:
        print("Batch sizes above 5 are not allowed.")
        print("Run full-text screening sequentially in batches of 5 or fewer.")
        sys.exit(1)

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)
    paths.screening.mkdir(parents=True, exist_ok=True)

    with connect(paths.db) as conn:
        # Records: title-included AND fulltext downloaded AND not yet
        # full-text screened (by anyone). We only want to batch records that
        # don't already have a `screening.pass='full_text'` decision.
        rows = conn.execute(
            """
            SELECT r.id, r.canonical_id, r.title, r.abstract, r.year,
                   r.first_author, r.venue, r.doi,
                   d.file_path, d.file_format
            FROM records r
            JOIN screening s_ta ON s_ta.record_id = r.id
                 AND s_ta.pass='title_abstract' AND s_ta.decision='include'
            JOIN downloads d ON d.record_id = r.id AND d.status='success'
            LEFT JOIN screening s_ft ON s_ft.record_id = r.id
                 AND s_ft.pass='full_text'
            WHERE s_ft.id IS NULL
            ORDER BY r.id
            LIMIT ?
            """,
            (args.batch_size,)
        ).fetchall()

        # Records included but not downloaded — for the not_downloaded report
        not_dl = conn.execute(
            """
            SELECT r.canonical_id, r.title, r.year, r.doi, r.url
            FROM records r
            JOIN screening s_ta ON s_ta.record_id = r.id
                 AND s_ta.pass='title_abstract' AND s_ta.decision='include'
            LEFT JOIN downloads d ON d.record_id = r.id AND d.status='success'
            WHERE d.id IS NULL
            ORDER BY r.id
            """
        ).fetchall()

    if not rows and not not_dl:
        print("Nothing ready for full-text screening yet.")
        print("Make sure you've run 04_screen_prep / 04b_screen_commit (or")
        print("04c_llm_screen), then 05_resolve_oa, then 06_download.")
        return

    # Write the not-downloaded report
    if not_dl:
        nd_path = paths.screening / "not_downloaded.txt"
        with open(nd_path, "w", encoding="utf-8") as f:
            f.write("# Records included at title/abstract but no OA full text.\n")
            f.write("# Use ILL or your library to obtain these.\n\n")
            for r in not_dl:
                f.write(f"- {r['canonical_id']} ({r['year']}) {r['title']}\n")
                if r['doi']:
                    f.write(f"  DOI: {r['doi']}\n")
                if r['url']:
                    f.write(f"  URL: {r['url']}\n")
                f.write("\n")
        print(f"{len(not_dl)} included records have no OA full text — see {nd_path}")

    if not rows:
        print("All downloaded full-text records already screened.")
        return

    # Pick batch number
    existing = sorted(paths.screening.glob("ft_batch_*.jsonl"))
    next_n = len(existing) + 1
    batch_path = paths.screening / f"ft_batch_{next_n:03d}.jsonl"
    batch_id = batch_path.stem

    # Refresh criteria sidecar (same one as 04 prep, but include a full-text note)
    crit_path = paths.screening / "_criteria.md"
    with open(crit_path, "w", encoding="utf-8") as f:
        f.write(f"# Criteria for {cfg.project_id} (full-text pass)\n\n")
        f.write(f"**Question:** {cfg.question}\n\n")
        f.write("Apply the same inclusion/exclusion criteria as the title/")
        f.write("abstract pass, but now you have the full paper. ")
        f.write("Common reasons to flip include→exclude at this stage: methods ")
        f.write("don't actually match what the abstract claimed; population ")
        f.write("turns out to be different; outcome wasn't measured the way ")
        f.write("the abstract implied.\n\n")
        f.write("## Inclusion\n")
        for c in cfg.inclusion:
            f.write(f"- **{c.get('id', '?')}**: {c.get('text', '')}\n")
        f.write("\n## Exclusion\n")
        for c in cfg.exclusion:
            f.write(f"- **{c.get('id', '?')}**: {c.get('text', '')}\n")

    extracted_count = 0
    conversion_failures = 0
    with open(batch_path, "w", encoding="utf-8") as f:
        for r in rows:
            full_path = (project_dir / r["file_path"]) if r["file_path"] else None
            text_excerpt = None
            intro_conclusion_excerpt = None
            markdown_rel_path = None
            markdown_error = None
            if full_path and full_path.exists():
                md_result = convert_to_markdown(
                    full_path,
                    markdown_dir=paths.fulltext_md,
                    max_chars=args.max_text_chars,
                )
                text_excerpt = md_result.excerpt
                intro_conclusion_excerpt = md_result.intro_conclusion_excerpt
                markdown_error = md_result.error
                if md_result.markdown_path:
                    markdown_rel_path = str(
                        md_result.markdown_path.relative_to(project_dir)
                    )

            if text_excerpt:
                extracted_count += 1
            else:
                conversion_failures += 1

            obj = {
                "record_id": r["id"],
                "canonical_id": r["canonical_id"],
                "title": r["title"],
                "abstract": r["abstract"],
                "year": r["year"],
                "first_author": r["first_author"],
                "venue": r["venue"],
                "doi": r["doi"],
                "file_path": r["file_path"],
                "file_format": r["file_format"],
                "markdown_path": markdown_rel_path,
                "markdown_error": markdown_error,
                "intro_conclusion_excerpt": intro_conclusion_excerpt,
                "fulltext_excerpt": text_excerpt,
                "batch_id": batch_id,
                "decision": None,
                "reason": None,
                "criteria_hit": [],
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(f"Batch written: {batch_path}")
    print(f"Records:       {len(rows)}")
    print(f"  with extracted text: {extracted_count}")
    print(f"  conversion failures: {conversion_failures}")
    print(f"Criteria:      {crit_path}")
    print()
    if conversion_failures:
        print("NOTE: some files could not be converted to Markdown.")
        print("Check each row's `markdown_error` and fall back to the raw file if needed.")
        print()
    if len(rows) > 100:
        print("Workflow note: this batch is over 100 records.")
        print("Run an intro/conclusion triage round before full-text reading.")
        print("Use each row's `intro_conclusion_excerpt` for that pass.")
        print()
    else:
        print("Workflow note: this batch is 100 records or fewer.")
        print("Ask the user whether they want an intro/conclusion triage round")
        print("before full-text reading. If yes, use `intro_conclusion_excerpt` first.")
        print()
    print("Agent: re-screen each record using the FULL TEXT, not just the")
    print("abstract. Then commit with:")
    print(f"  python scripts/07b_fulltext_commit.py --batch {batch_path}")


if __name__ == "__main__":
    main()

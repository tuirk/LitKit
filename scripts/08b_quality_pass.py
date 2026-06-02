#!/usr/bin/env python3
"""Standalone PRISMA risk-of-bias / critical-appraisal assessment.

Runs risk-of-bias assessment over already-included papers that don't yet have
RoB data. Uses the LLM configured in project.yaml. Reads the full text from
disk if it was downloaded, falls back to abstract-only if not.

Use this when:
- You finished screening before doing risk-of-bias assessment.
- You used 07c_llm_fulltext WITHOUT --with-quality and want to add it.
- You did manual full-text screening and now need PRISMA RoB data.

The script is idempotent — it skips records that already have quality data
from the same provider.

Usage:
  python scripts/08b_quality_pass.py --project <id>
  python scripts/08b_quality_pass.py --project <id> --max 50
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import ProjectConfig, ProjectPaths, connect, log_event
from slr_engine.fulltext_markdown import convert_to_markdown
from slr_engine.llm import (
    extract_record, get_extraction_fields, LLMError, QUALITY_FIELDS,
    build_extract_prompt_packet,
)
from slr_engine.agent_handoff import make_packet, write_jsonl


def _stage_agent_quality_batch(*, project_dir: Path, paths: ProjectPaths,
                               cfg: ProjectConfig, candidates, fields: list[dict],
                               max_text_chars: int) -> Path:
    existing = sorted(paths.screening.glob("quality_batch_*.jsonl"))
    next_n = len(existing) + 1
    batch_path = paths.screening / f"quality_batch_{next_n:03d}.jsonl"
    prompts_path = paths.screening / f"{batch_path.stem}_prompts.jsonl"

    with open(batch_path, "w", encoding="utf-8") as f:
        for r in candidates:
            fulltext_excerpt = None
            if r["file_path"]:
                full_path = project_dir / r["file_path"]
                if full_path.exists():
                    md_result = convert_to_markdown(
                        full_path,
                        markdown_dir=paths.fulltext_md,
                        max_chars=max_text_chars,
                    )
                    fulltext_excerpt = md_result.excerpt

            obj = {
                "record_id": r["id"],
                "canonical_id": r["canonical_id"],
                "title": r["title"],
                "abstract": r["abstract"],
                "year": r["year"],
                "venue": r["venue"],
                "doi": r["doi"],
                "file_path": r["file_path"],
                "fulltext_excerpt": fulltext_excerpt,
                "fields": {field["name"]: "" for field in fields},
                "quality": {
                    "risk_of_bias_tool": "",
                    "risk_of_bias_overall": "",
                    "risk_of_bias_domains": [],
                    "risk_of_bias_notes": "",
                    "methodological_rigor": "",
                    "evidence_strength": "",
                    "limitations_acknowledged": "",
                    "quality_notes": "",
                },
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    prompt_packets = []
    for r in candidates:
        fulltext_excerpt = None
        if r["file_path"]:
            full_path = project_dir / r["file_path"]
            if full_path.exists():
                md_result = convert_to_markdown(
                    full_path,
                    markdown_dir=paths.fulltext_md,
                    max_chars=max_text_chars,
                )
                fulltext_excerpt = md_result.excerpt
        prompt_packets.append(
            make_packet(
                stage="quality_assessment",
                project_id=cfg.project_id,
                item={
                    "record_id": r["id"],
                    "canonical_id": r["canonical_id"],
                },
                prompt=build_extract_prompt_packet(
                    question=cfg.review_question_for_llm(),
                    record={
                        "title": r["title"],
                        "abstract": r["abstract"],
                        "year": r["year"],
                        "venue": r["venue"],
                        "fulltext_excerpt": fulltext_excerpt,
                    },
                    fields=fields,
                    with_quality=True,
                ),
                input_refs={
                    "quality_batch": str(batch_path),
                },
                output={
                    "write_back_to": str(batch_path),
                    "fields": ["fields", "quality"],
                    "commit_command": f"python scripts/08c_quality_commit.py --batch {batch_path}",
                },
            )
        )
    write_jsonl(prompts_path, prompt_packets)

    request_path = paths.screening / f"{batch_path.stem}_agent_request.md"
    with open(request_path, "w", encoding="utf-8") as f:
        f.write("# Agent risk-of-bias assessment request\n\n")
        f.write("This project is in agent mode. An external coding agent should\n")
        f.write("populate each row's `quality` object with PRISMA risk-of-bias\n")
        f.write("fields and, if useful, refresh the\n")
        f.write("generic extraction `fields`, then commit with:\n\n")
        f.write(f"Prompt packets: `{prompts_path.name}`\n\n")
        f.write(f"`python scripts/08c_quality_commit.py --batch {batch_path}`\n")

    print("Agent mode detected: staged quality batch for external agent.")
    print()
    print(f"Batch written: {batch_path}")
    print(f"Prompts:       {prompts_path}")
    print(f"Request:       {request_path}")
    print()
    print("Next: have the external agent fill the batch and commit with:")
    print(f"  python scripts/08c_quality_commit.py --batch {batch_path}")
    return batch_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max", type=int, default=10000)
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--max-text-chars", type=int, default=30000)
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)

    provider = cfg.judgment_provider()
    model = cfg.judgment_model()
    temp = float((cfg.llm or {}).get("temperature", 0.0))
    extracted_by = f"llm:{provider}:risk_of_bias"

    fields = get_extraction_fields(getattr(cfg, "extraction", None))

    # Find included papers that lack risk-of-bias data from this provider.
    # Prefer full-text-included papers; fall back to title/abstract includes
    # if no full-text pass has happened.
    with connect(paths.db) as conn:
        candidates = conn.execute(
            """
            SELECT r.id, r.canonical_id, r.title, r.abstract, r.year,
                   r.venue, r.doi, d.file_path
            FROM records r
            LEFT JOIN downloads d
              ON d.record_id = r.id AND d.status='success'
            WHERE r.id IN (
              SELECT record_id FROM screening
              WHERE pass='full_text' AND decision='include'
                AND decided_by='human'
            )
            AND r.id NOT IN (
              SELECT record_id FROM extractions
                WHERE extracted_by = ?
                AND risk_of_bias_overall IS NOT NULL
            )
            ORDER BY r.id LIMIT ?
            """,
            (extracted_by, args.max),
        ).fetchall()

        if not candidates:
            # Fall back to title/abstract includes
            candidates = conn.execute(
                """
                SELECT r.id, r.canonical_id, r.title, r.abstract, r.year,
                       r.venue, r.doi, d.file_path
                FROM records r
                LEFT JOIN downloads d
                  ON d.record_id = r.id AND d.status='success'
                WHERE r.id IN (
                  SELECT record_id FROM screening
                  WHERE pass='title_abstract' AND decision='include'
                )
                AND r.id NOT IN (
                  SELECT record_id FROM extractions
                  WHERE extracted_by = ?
                    AND risk_of_bias_overall IS NOT NULL
                )
                ORDER BY r.id LIMIT ?
                """,
                (extracted_by, args.max),
            ).fetchall()

    if not candidates:
        print("No included papers need risk-of-bias assessment.")
        return

    if cfg.uses_agent_judgment():
        _stage_agent_quality_batch(
            project_dir=project_dir,
            paths=paths,
            cfg=cfg,
            candidates=candidates,
            fields=fields,
            max_text_chars=args.max_text_chars,
        )
        return

    print(f"Running risk-of-bias pass on {len(candidates)} papers via {provider} ({model})")
    print()

    failures = 0
    chars_total = 0
    for i, r in enumerate(candidates, 1):
        # Try to load the full text
        fulltext_excerpt = None
        if r["file_path"]:
            full_path = project_dir / r["file_path"]
            if full_path.exists():
                md_result = convert_to_markdown(
                    full_path,
                    markdown_dir=paths.fulltext_md,
                    max_chars=args.max_text_chars,
                )
                fulltext_excerpt = md_result.excerpt

        record_payload = {
            "title": r["title"],
            "abstract": r["abstract"],
            "year": r["year"],
            "venue": r["venue"],
            "fulltext_excerpt": fulltext_excerpt,
        }
        try:
            result = extract_record(
                provider=provider,
                model=model,
                question=cfg.review_question_for_llm(),
                record=record_payload,
                fields=fields,
                with_quality=True,
                temperature=temp,
            )
        except (LLMError, Exception) as e:
            failures += 1
            print(f"  [error] {r['canonical_id']}: {e}")
            with connect(paths.db) as conn:
                log_event(conn, "extract", "error", str(e),
                          {"record_id": r["id"]})
            time.sleep(args.sleep)
            continue

        chars_seen = len(fulltext_excerpt or "")
        chars_total += chars_seen
        with connect(paths.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO extractions "
                "(record_id, fields_json, methodological_rigor, "
                " evidence_strength, limitations_acknowledged, quality_notes, "
                " risk_of_bias_tool, risk_of_bias_overall, "
                " risk_of_bias_domains_json, risk_of_bias_notes, "
                " extracted_by, source_text_chars) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["id"],
                    json.dumps(result.fields),
                    (result.quality or {}).get("methodological_rigor"),
                    (result.quality or {}).get("evidence_strength"),
                    (result.quality or {}).get("limitations_acknowledged"),
                    (result.quality or {}).get("quality_notes"),
                    (result.quality or {}).get("risk_of_bias_tool"),
                    (result.quality or {}).get("risk_of_bias_overall"),
                    json.dumps((result.quality or {}).get("risk_of_bias_domains") or []),
                    (result.quality or {}).get("risk_of_bias_notes"),
                    extracted_by,
                    chars_seen,
                ),
            )

        if i % 10 == 0:
            print(f"  ...{i}/{len(candidates)}")
        time.sleep(args.sleep)

    print()
    print(f"Risk-of-bias pass complete. Failures: {failures}")
    print(f"Total full-text chars seen: {chars_total}")
    print()
    print("Risk-of-bias data now available in the extractions table for export.")


if __name__ == "__main__":
    main()

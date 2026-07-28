#!/usr/bin/env python3
"""LLM full-text pass: combined screen + extract (+ optional risk of bias).

Reads the batch produced by 07_fulltext_prep, sends each record to the
configured LLM with the full-text excerpt, and gets back BOTH a screening
recommendation AND extraction fields in one call.

Decisions are staged as `decided_by='llm:<provider>:recommendation'` —
NOT final. Run 07d_human_review.py to confirm/override and produce
final `decided_by='human'` decisions.

Usage:
  python scripts/07c_llm_fulltext.py --project <id> --batch <path>
  python scripts/07c_llm_fulltext.py --project <id> --batch <path> --with-quality

PRISMA-oriented risk-of-bias assessment is controlled by --with-quality
(legacy flag name). The agent should suggest it after reading
skills/slr-engine/SKILL_quality_assessment.md.
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import ProjectConfig, ProjectPaths, connect, log_event
from slr_engine.llm import (
    screen_and_extract, get_extraction_fields, LLMError, QUALITY_FIELDS,
    build_combined_prompt_packet,
)
from slr_engine.agent_handoff import make_packet, write_jsonl


def _stage_agent_fulltext_review(*, cfg: ProjectConfig, batch_path: Path,
                                 review_path: Path, records: list[dict],
                                 with_quality: bool, fields: list[dict],
                                 field_names: list[str]) -> None:
    prompts_path = review_path.with_name(review_path.stem + "_prompts.jsonl")
    with open(review_path, "w", encoding="utf-8") as f:
        for rec in records:
            review_line = {
                "record_id": rec["record_id"],
                "canonical_id": rec.get("canonical_id"),
                "title": rec.get("title"),
                "year": rec.get("year"),
                "venue": rec.get("venue"),
                "doi": rec.get("doi"),
                "abstract": rec.get("abstract"),
                "intro_conclusion_excerpt": rec.get("intro_conclusion_excerpt"),
                "fulltext_excerpt": rec.get("fulltext_excerpt"),
                "extraction": {name: "" for name in field_names},
                "quality": None if not with_quality else {
                    "risk_of_bias_tool": "",
                    "risk_of_bias_overall": "",
                    "risk_of_bias_domains": [],
                    "risk_of_bias_notes": "",
                    "methodological_rigor": "",
                    "evidence_strength": "",
                    "limitations_acknowledged": "",
                    "quality_notes": "",
                },
                "llm_recommendation": {
                    "decision": None,
                    "reason": "",
                    "criteria_hit": [],
                },
                "your_decision": None,
                "your_reason": None,
                "criteria_hit": [],
            }
            f.write(json.dumps(review_line, ensure_ascii=False) + "\n")

    prompt_packets = []
    for rec in records:
        record_payload = {
            "title": rec.get("title"),
            "abstract": rec.get("abstract"),
            "year": rec.get("year"),
            "venue": rec.get("venue"),
            "intro_conclusion_excerpt": rec.get("intro_conclusion_excerpt"),
            "fulltext_excerpt": rec.get("fulltext_excerpt"),
        }
        prompt_packets.append(
            make_packet(
                stage="full_text_screen_extract",
                project_id=cfg.project_id,
                item={
                    "record_id": rec["record_id"],
                    "canonical_id": rec.get("canonical_id"),
                },
                prompt=build_combined_prompt_packet(
                    question=cfg.review_question_for_llm(),
                    inclusion=cfg.inclusion,
                    exclusion=cfg.exclusion,
                    seed_examples=cfg.seed_examples,
                    record=record_payload,
                    fields=fields,
                    with_quality=with_quality,
                ),
                input_refs={
                    "source_batch": str(batch_path),
                    "review_file": str(review_path),
                },
                output={
                    "write_back_to": str(review_path),
                    "fields": [
                        "llm_recommendation.decision",
                        "llm_recommendation.reason",
                        "llm_recommendation.criteria_hit",
                        "extraction",
                    ] + (["quality"] if with_quality else []),
                    "commit_command": f"python scripts/07d_human_review.py --review {review_path} --print-summary",
                },
            )
        )
    write_jsonl(prompts_path, prompt_packets)

    request_path = review_path.with_name(review_path.stem + "_agent_request.md")
    with open(request_path, "w", encoding="utf-8") as f:
        f.write("# Agent full-text review request\n\n")
        f.write("This project is in agent mode. An external coding agent should\n")
        f.write("read the source batch and populate each review row with:\n")
        f.write("- `llm_recommendation.decision`\n")
        f.write("- `llm_recommendation.reason`\n")
        f.write("- `llm_recommendation.criteria_hit`\n")
        f.write("- `extraction`\n")
        if with_quality:
            f.write("- `quality`\n")
        f.write(f"\nPrompt packets: `{prompts_path.name}`\n")
        f.write("\nThen run:\n")
        f.write(f"`python scripts/07d_human_review.py --review {review_path} --print-summary`\n")

    print("Agent mode detected: staged full-text review file for external agent.")
    print()
    print(f"Source batch: {batch_path}")
    print(f"Review file:  {review_path}")
    print(f"Prompts:      {prompts_path}")
    print(f"Request:      {request_path}")
    print()
    print("Next: have the external agent fill the review file, then run:")
    print(f"  python scripts/07d_human_review.py --review {review_path} --print-summary")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--batch", required=True,
                    help="Path to ft_batch_NNN.jsonl from 07_fulltext_prep")
    ap.add_argument("--with-quality", action="store_true",
                    help="Also produce PRISMA risk-of-bias / critical-appraisal fields")
    ap.add_argument("--max", type=int, default=10000)
    ap.add_argument("--sleep", type=float, default=0.5)
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
    if not cfg.uses_agent_judgment() and (not provider or not model):
        print("project.yaml `llm:` block needs both `provider` and `model`.")
        print("If you want external-agent review instead, set")
        print("`llm.provider: agent` or leave `llm: null` and re-run.")
        sys.exit(1)
    decided_by = f"llm:{provider}:recommendation"
    extracted_by = f"llm:{provider}"

    fields = get_extraction_fields(getattr(cfg, "extraction", None))

    batch_path = Path(args.batch).resolve()
    if not batch_path.exists():
        print(f"Batch not found: {batch_path}")
        sys.exit(1)

    # Load the prep batch
    records = []
    # Batches are written as UTF-8 JSONL. Some Windows tools may accidentally add a UTF-8 BOM;
    # accept that by using utf-8-sig while remaining resilient to other encoding issues.
    with open(batch_path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if args.max and len(records) > args.max:
        records = records[: args.max]

    review_path = paths.screening / batch_path.name.replace(
        "ft_batch_", "ft_review_"
    )
    if review_path == batch_path:
        review_path = paths.screening / f"ft_review_{batch_path.stem}.jsonl"

    print(f"Processing {len(records)} records via {provider} ({model})")
    print(f"  with_quality: {args.with_quality}")
    print(f"  extraction fields: {[f['name'] for f in fields]}")
    print()

    if cfg.uses_agent_judgment():
        _stage_agent_fulltext_review(
            cfg=cfg,
            batch_path=batch_path,
            review_path=review_path,
            records=records,
            with_quality=args.with_quality,
            fields=fields,
            field_names=[f["name"] for f in fields],
        )
        return

    counts = {"include": 0, "exclude": 0, "unsure": 0}
    failures = 0
    review_lines = []

    for i, rec in enumerate(records, 1):
        record_payload = {
            "title": rec.get("title"),
            "abstract": rec.get("abstract"),
            "year": rec.get("year"),
            "venue": rec.get("venue"),
            "intro_conclusion_excerpt": rec.get("intro_conclusion_excerpt"),
            "fulltext_excerpt": rec.get("fulltext_excerpt"),
        }
        try:
            result = screen_and_extract(
                provider=provider,
                model=model,
                question=cfg.review_question_for_llm(),
                inclusion=cfg.inclusion,
                exclusion=cfg.exclusion,
                seed_examples=cfg.seed_examples,
                record=record_payload,
                fields=fields,
                with_quality=args.with_quality,
                temperature=temp,
            )
        except (LLMError, Exception) as e:
            failures += 1
            err = f"{type(e).__name__}: {e}"
            print(f"  [error] {rec.get('canonical_id')}: {err}")
            with connect(paths.db) as conn:
                log_event(conn, "screen", "error", err,
                          {"record_id": rec.get("record_id"),
                           "stage": "07c_llm_fulltext"})
            time.sleep(args.sleep)
            continue

        counts[result.screening.decision] += 1

        # Stage 1: write LLM screening recommendation to DB
        with connect(paths.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO screening "
                "(record_id, pass, decision, reason, criteria_hit, "
                " decided_by, batch_id) "
                "VALUES (?,'full_text',?,?,?,?,?)",
                (
                    rec["record_id"],
                    result.screening.decision,
                    result.screening.reason,
                    json.dumps(result.screening.criteria_hit),
                    decided_by,
                    review_path.stem,
                ),
            )

            # Stage 2: write extraction
            chars_seen = len(rec.get("fulltext_excerpt") or "")
            conn.execute(
                "INSERT OR REPLACE INTO extractions "
                "(record_id, fields_json, methodological_rigor, "
                " evidence_strength, limitations_acknowledged, quality_notes, "
                " risk_of_bias_tool, risk_of_bias_overall, "
                " risk_of_bias_domains_json, risk_of_bias_notes, "
                " extracted_by, source_text_chars) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rec["record_id"],
                    json.dumps(result.extraction.fields),
                    (result.extraction.quality or {}).get("methodological_rigor"),
                    (result.extraction.quality or {}).get("evidence_strength"),
                    (result.extraction.quality or {}).get("limitations_acknowledged"),
                    (result.extraction.quality or {}).get("quality_notes"),
                    (result.extraction.quality or {}).get("risk_of_bias_tool"),
                    (result.extraction.quality or {}).get("risk_of_bias_overall"),
                    json.dumps((result.extraction.quality or {}).get("risk_of_bias_domains") or []),
                    (result.extraction.quality or {}).get("risk_of_bias_notes"),
                    extracted_by,
                    chars_seen,
                ),
            )

        # Build review line for the human-review file
        review_lines.append({
            "record_id": rec["record_id"],
            "canonical_id": rec.get("canonical_id"),
            "title": rec.get("title"),
            "year": rec.get("year"),
            "venue": rec.get("venue"),
            "doi": rec.get("doi"),
            "abstract": rec.get("abstract"),
            "intro_conclusion_excerpt": rec.get("intro_conclusion_excerpt"),
            "extraction": result.extraction.fields,
            "quality": result.extraction.quality,
            "llm_recommendation": {
                "decision": result.screening.decision,
                "reason": result.screening.reason,
                "criteria_hit": result.screening.criteria_hit,
            },
            "your_decision": None,
            "your_reason": None,
            "criteria_hit": [],
        })

        if i % 10 == 0:
            print(f"  ...{i}/{len(records)}  inc={counts['include']} "
                  f"exc={counts['exclude']} uns={counts['unsure']} "
                  f"err={failures}")
        time.sleep(args.sleep)

    # Write the human-review file
    with open(review_path, "w", encoding="utf-8") as f:
        for line in review_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    with connect(paths.db) as conn:
        log_event(conn, "screen", "info",
                  f"LLM full-text pass complete: {decided_by}",
                  {"counts": counts, "failures": failures,
                   "with_quality": args.with_quality, "model": model})

    print()
    print(f"LLM full-text pass complete.")
    print(f"  Recommendations: include={counts['include']} "
          f"exclude={counts['exclude']} unsure={counts['unsure']}")
    if failures:
        print(f"  Failures: {failures} (see events log)")
    print()
    print(f"Review file: {review_path}")
    print()
    print("Next: have the agent walk you through review.")
    print(f"  python scripts/07d_human_review.py --review {review_path}")


if __name__ == "__main__":
    main()

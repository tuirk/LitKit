#!/usr/bin/env python3
"""LLM-driven title/abstract screening (optional).

This is the unattended path. The default flow is `04_screen_prep` →
agent-labels-by-hand → `04b_screen_commit`. This script replaces those
two with an LLM batch call, suitable when you have hundreds of records
and your `project.yaml` has an `llm:` block configured.

Provider/model/temperature come from project.yaml's `llm:` block.
API keys come from environment variables:
  - ANTHROPIC_API_KEY for provider=anthropic
  - DEEPSEEK_API_KEY for provider=deepseek
  - GOOGLE_API_KEY for provider=google

Decisions are written with decided_by='llm:<provider>' so they don't
collide with manual agent decisions or human review.

Usage:
  python scripts/04c_llm_screen.py --project <id>
  python scripts/04c_llm_screen.py --project <id> --max 100
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import ProjectConfig, ProjectPaths, connect, log_event
from slr_engine.llm import screen_record, LLMError, build_screen_prompt_packet
from slr_engine.agent_handoff import make_packet, write_jsonl


def _write_agent_screening_batch(cfg: ProjectConfig, paths: ProjectPaths,
                                 pass_name: str, max_records: int) -> Path | None:
    with connect(paths.db) as conn:
        rows = conn.execute(
            "SELECT r.id, r.canonical_id, r.title, r.abstract, r.year, "
            "r.first_author, r.venue, r.doi "
            "FROM records r "
            "LEFT JOIN screening s ON s.record_id = r.id AND s.pass = ? AND s.decided_by = 'agent' "
            "WHERE s.id IS NULL "
            "ORDER BY r.id LIMIT ?",
            (pass_name, max_records),
        ).fetchall()

    if not rows:
        return None

    existing = sorted(paths.screening.glob("batch_*.jsonl"))
    next_n = len(existing) + 1
    batch_path = paths.screening / f"batch_{next_n:03d}.jsonl"
    batch_id = batch_path.stem
    prompts_path = paths.screening / f"{batch_id}_prompts.jsonl"

    crit_path = paths.screening / "_criteria.md"
    with open(crit_path, "w", encoding="utf-8") as f:
        f.write(f"# Criteria for {cfg.project_id}\n\n")
        f.write(f"**Question:** {cfg.question}\n\n")
        f.write("## Inclusion\n")
        for c in cfg.inclusion:
            f.write(f"- **{c.get('id', '?')}**: {c.get('text', '')}\n")
        f.write("\n## Exclusion\n")
        for c in cfg.exclusion:
            f.write(f"- **{c.get('id', '?')}**: {c.get('text', '')}\n")
        f.write("\n## Seed examples\n\n")
        f.write("### Should INCLUDE:\n")
        for s in cfg.seed_examples.get("include", []):
            f.write(f"- {s}\n")
        f.write("\n### Should EXCLUDE:\n")
        for s in cfg.seed_examples.get("exclude", []):
            f.write(f"- {s}\n")

    with open(batch_path, "w", encoding="utf-8") as f:
        for r in rows:
            obj = {
                "record_id": r["id"],
                "canonical_id": r["canonical_id"],
                "title": r["title"],
                "abstract": r["abstract"],
                "year": r["year"],
                "first_author": r["first_author"],
                "venue": r["venue"],
                "doi": r["doi"],
                "batch_id": batch_id,
                "decision": None,
                "reason": None,
                "criteria_hit": [],
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    prompt_packets = []
    for r in rows:
        record = {
            "title": r["title"],
            "abstract": r["abstract"],
            "year": r["year"],
            "venue": r["venue"],
        }
        prompt_packets.append(
            make_packet(
                stage="title_abstract_screening",
                project_id=cfg.project_id,
                item={
                    "record_id": r["id"],
                    "canonical_id": r["canonical_id"],
                },
                prompt=build_screen_prompt_packet(
                    question=cfg.review_question_for_llm(),
                    inclusion=cfg.inclusion,
                    exclusion=cfg.exclusion,
                    seed_examples=cfg.seed_examples,
                    record=record,
                ),
                input_refs={
                    "batch_file": str(batch_path),
                    "criteria_file": str(crit_path),
                },
                output={
                    "write_back_to": str(batch_path),
                    "fields": ["decision", "reason", "criteria_hit"],
                    "commit_command": f"python scripts/04b_screen_commit.py --batch {batch_path}",
                },
            )
        )
    write_jsonl(prompts_path, prompt_packets)

    request_path = paths.screening / f"{batch_id}_agent_request.md"
    with open(request_path, "w", encoding="utf-8") as f:
        f.write("# Agent screening request\n\n")
        f.write("This project is in agent mode. An external coding agent should\n")
        f.write("screen the attached batch against `_criteria.md`, fill each JSONL\n")
        f.write("row's `decision`, `reason`, and `criteria_hit`, then commit with:\n\n")
        f.write(f"Prompt packets: `{prompts_path.name}`\n\n")
        f.write(f"`python scripts/04b_screen_commit.py --batch {batch_path}`\n")

    print("Agent mode detected: staging screening batch for external agent.")
    print()
    print(f"Batch written: {batch_path}")
    print(f"Records:       {len(rows)}")
    print(f"Criteria:      {crit_path}")
    print(f"Prompts:       {prompts_path}")
    print(f"Request:       {request_path}")
    print()
    print("Next: have the external agent label the batch and commit with:")
    print(f"  python scripts/04b_screen_commit.py --batch {batch_path}")
    return batch_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max", type=int, default=10000,
                    help="Maximum records to label this run")
    ap.add_argument("--sleep", type=float, default=0.3,
                    help="Seconds between API calls")
    ap.add_argument("--pass-name", default="title_abstract")
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)

    if cfg.uses_agent_judgment():
        _write_agent_screening_batch(
            cfg=cfg,
            paths=paths,
            pass_name=args.pass_name,
            max_records=args.max,
        )
        return

    provider = cfg.llm.get("provider")
    model = cfg.llm.get("model")
    temp = float(cfg.llm.get("temperature", 0.0))
    decided_by = f"llm:{provider}"

    if not provider or not model:
        print("project.yaml `llm:` block needs both `provider` and `model`.")
        print("If you want Codex/Claude Code/manual agent screening instead,")
        print("set `llm.provider: agent` or leave `llm: null` and re-run.")
        sys.exit(1)

    # Pull all unscreened records (for this decided_by tag specifically)
    with connect(paths.db) as conn:
        rows = conn.execute(
            "SELECT r.id, r.title, r.abstract, r.year, r.venue, r.first_author "
            "FROM records r "
            "LEFT JOIN screening s ON s.record_id = r.id AND s.pass = ? AND s.decided_by = ? "
            "WHERE s.id IS NULL "
            "ORDER BY r.id LIMIT ?",
            (args.pass_name, decided_by, args.max),
        ).fetchall()

    if not rows:
        print(f"No unscreened records for {decided_by} pass={args.pass_name}.")
        return

    print(f"Screening {len(rows)} records via {provider} ({model})...")

    counts = {"include": 0, "exclude": 0, "unsure": 0}
    failures = 0

    for i, r in enumerate(rows, 1):
        record = {
            "title": r["title"],
            "abstract": r["abstract"],
            "year": r["year"],
            "venue": r["venue"],
        }
        try:
            result = screen_record(
                provider=provider,
                model=model,
                question=cfg.review_question_for_llm(),
                inclusion=cfg.inclusion,
                exclusion=cfg.exclusion,
                seed_examples=cfg.seed_examples,
                record=record,
                temperature=temp,
            )
        except LLMError as e:
            failures += 1
            print(f"  [error] record {r['id']}: {e}")
            with connect(paths.db) as conn:
                log_event(conn, "screen", "error", str(e),
                          {"record_id": r["id"], "decided_by": decided_by})
            time.sleep(args.sleep)
            continue
        except Exception as e:
            failures += 1
            print(f"  [error] record {r['id']}: {e}")
            with connect(paths.db) as conn:
                log_event(conn, "screen", "error",
                          f"unexpected: {e}\n{traceback.format_exc()[:300]}",
                          {"record_id": r["id"]})
            time.sleep(args.sleep)
            continue

        counts[result.decision] += 1
        with connect(paths.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO screening "
                "(record_id, pass, decision, reason, criteria_hit, "
                " decided_by, batch_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (r["id"], args.pass_name, result.decision, result.reason,
                 json.dumps(result.criteria_hit), decided_by,
                 f"llm_run_{provider}"),
            )
        if i % 25 == 0:
            print(f"  ...{i}/{len(rows)}  "
                  f"(inc {counts['include']}, exc {counts['exclude']}, "
                  f"uns {counts['unsure']}, err {failures})")
        time.sleep(args.sleep)

    with connect(paths.db) as conn:
        log_event(conn, "screen", "info",
                  f"LLM screening complete: {decided_by}",
                  {"counts": counts, "failures": failures, "model": model})

    print()
    print(f"LLM screening done. decided_by={decided_by}")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if failures:
        print(f"  failed:  {failures} (logged in events table)")
    print()
    print("Recommended next: have the agent review unsures, and spot-check")
    print("a sample of LLM excludes to validate calibration. Then proceed.")


if __name__ == "__main__":
    main()

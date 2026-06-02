#!/usr/bin/env python3
"""Extract vocabulary from seed papers via KeyBERT + LLM curation.

Two-stage process:
  1. KeyBERT pulls ~30-50 candidate phrases from seed text (statistical,
     grounded). If keybert isn't installed, falls back to a frequency
     heuristic and warns the user — the agent should ask the user to
     install keybert before proceeding for proper extraction.
  2. The configured LLM curates the bucket: picks strong terms, drops
     weak ones, adds known synonyms only for bucketed phrases, groups
     into concept clusters.

Output goes to projects/<id>/seeds/_vocabulary.json. The agent shows it
to the user, gets confirmation, then uses the clusters as input for
PICOC slot proposal.

Usage:
  python scripts/00c_extract_vocabulary.py --project <slug>
  python scripts/00c_extract_vocabulary.py --project <slug> --no-llm
      # skip LLM curation, just produce KeyBERT bucket. For dry runs.
  python scripts/00c_extract_vocabulary.py --project <slug> --top-n 60
      # extract more candidate phrases from KeyBERT
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import ProjectConfig, ProjectPaths, connect, log_event
from slr_engine.seeds import load_seed_records
from slr_engine.vocab import (
    extract_with_keybert, prompt_llm_to_curate, build_seed_text_summary,
    keybert_available, build_vocab_curation_prompt_packet,
)
from slr_engine.agent_handoff import make_packet, write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--top-n", type=int, default=50,
                    help="KeyBERT candidate phrase count (default 50)")
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip LLM curation — just produce KeyBERT bucket")
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)
    seeds_dir = project_dir / "seeds"

    # Load seed records produced by 00b_read_seeds.py
    seed_records = load_seed_records(seeds_dir)
    if not seed_records:
        print(f"No seed records found in {seeds_dir}/")
        print()
        print("Run scripts/00b_read_seeds.py first to read your seeds.")
        sys.exit(1)

    valid_seeds = [r for r in seed_records if not r.error]
    errored_seeds = [r for r in seed_records if r.error]
    if not valid_seeds:
        print(f"All {len(seed_records)} seeds have errors. Cannot extract")
        print("vocabulary without at least one usable seed.")
        for r in errored_seeds:
            print(f"  {r.seed_id}: {r.error}")
        sys.exit(1)

    if errored_seeds:
        print(f"WARNING: {len(errored_seeds)} seed(s) had errors and will be skipped.")
        for r in errored_seeds:
            print(f"  {r.seed_id}: {r.error}")
        print()

    # Convert to dicts for vocab module
    seed_dicts = [r.to_json() for r in valid_seeds]

    # Stage 1: KeyBERT
    if keybert_available():
        print(f"Stage 1: Running KeyBERT over {len(valid_seeds)} seed(s)...")
        print("(First run downloads the sentence-transformer model — ~80MB)")
    else:
        print("WARNING: keybert is not installed. Falling back to frequency-based")
        print("extraction, which is significantly worse than KeyBERT.")
        print()
        print("To install KeyBERT (recommended):")
        print("  pip install keybert sentence-transformers")
        print()
        print("Continuing with fallback extractor...")

    candidates = extract_with_keybert(seed_dicts, top_n=args.top_n)

    print(f"  Got {len(candidates)} candidate phrases.")
    print()
    print("Top 20 candidate phrases:")
    for i, c in enumerate(candidates[:20], 1):
        print(f"  {i:3d}. {c.phrase} (score={c.score:.2f}, in_seeds={c.seed_count})")
    if len(candidates) > 20:
        print(f"  ... and {len(candidates) - 20} more")
    print()

    # Save the raw KeyBERT output regardless of whether we run LLM curation
    keybert_path = seeds_dir / "_keybert_bucket.json"
    with open(keybert_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"phrase": c.phrase, "score": c.score, "seed_count": c.seed_count}
             for c in candidates],
            f, indent=2, ensure_ascii=False
        )

    if args.no_llm:
        print(f"Wrote KeyBERT bucket to {keybert_path}")
        print()
        print("Skipped LLM curation per --no-llm. Re-run without that flag")
        print("to produce the curated vocabulary.")
        return

    # Stage 2: LLM curation
    if cfg.uses_agent_judgment():
        request_path = seeds_dir / "_vocabulary_agent_request.md"
        prompt_path = seeds_dir / "_vocabulary_prompt.json"
        prompt_packet = make_packet(
            stage="vocabulary_curation",
            project_id=cfg.project_id,
            item={"project_id": cfg.project_id},
            prompt=build_vocab_curation_prompt_packet(
                keybert_output=candidates,
                seed_text_summary=build_seed_text_summary(seed_dicts),
            ),
            input_refs={
                "keybert_bucket": str(keybert_path),
                "seed_records_glob": str(seeds_dir / "seed_*.json"),
            },
            output={
                "write_to": str(seeds_dir / "_vocabulary.json"),
                "format": "json",
            },
        )
        write_json(prompt_path, prompt_packet)
        with open(request_path, "w", encoding="utf-8") as f:
            f.write("# Agent vocabulary curation request\n\n")
            f.write("The project is in agent mode, so vocabulary curation is\n")
            f.write("performed by the external coding agent rather than an API\n")
            f.write("provider.\n\n")
            f.write("Inputs:\n")
            f.write(f"- Raw KeyBERT bucket: `{keybert_path.name}`\n")
            f.write("- Seed metadata: `seed_*.json`\n\n")
            f.write(f"- Prompt packet: `{prompt_path.name}`\n\n")
            f.write("Required output:\n")
            f.write("- `seeds/_vocabulary.json`\n\n")
            f.write("Use the system/user prompts in the JSON packet directly.\n")

        print("Agent mode detected: skipping API-backed vocabulary curation.")
        print()
        print(f"KeyBERT bucket saved to {keybert_path}")
        print(f"Prompt packet saved to {prompt_path}")
        print(f"Agent handoff written to {request_path}")
        print()
        print("Next: have the external agent review the bucket and write")
        print("`seeds/_vocabulary.json`, then continue to query generation.")
        return

    print(f"Stage 2: LLM curation via {cfg.llm.get('provider')}/{cfg.llm.get('model')}...")
    seed_summary = build_seed_text_summary(seed_dicts)

    try:
        curated = prompt_llm_to_curate(
            keybert_output=candidates,
            seed_text_summary=seed_summary,
            llm_config=cfg.llm,
        )
    except Exception as e:
        print(f"  ERROR: LLM curation failed: {type(e).__name__}: {e}")
        print()
        print(f"KeyBERT bucket saved to {keybert_path}")
        print("You can manually curate from there, or fix the LLM config and re-run.")
        with connect(paths.db) as conn:
            log_event(
                conn, "scoping", "error",
                f"LLM vocabulary curation failed: {e}",
                {"project_id": cfg.project_id}
            )
        sys.exit(1)

    # Persist curated vocabulary
    vocab_path = seeds_dir / "_vocabulary.json"
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(curated, f, indent=2, ensure_ascii=False)

    with connect(paths.db) as conn:
        log_event(
            conn, "scoping", "info",
            f"Vocabulary extracted: {len(curated.get('clusters', []))} clusters",
            {"project_id": cfg.project_id,
             "keybert_count": len(candidates),
             "clusters": len(curated.get("clusters", [])),
             "dropped": len(curated.get("dropped", [])),
             "added_synonyms": len(curated.get("added_synonyms", []))}
        )

    # Report
    print()
    print(f"Curated vocabulary saved to {vocab_path}")
    print()
    print("=" * 60)
    print("CURATED VOCABULARY (review before continuing)")
    print("=" * 60)
    for cluster in curated.get("clusters", []):
        print()
        print(f"Cluster: {cluster['name']}")
        if cluster.get("rationale"):
            print(f"  Why: {cluster['rationale']}")
        for term in cluster["terms"]:
            print(f"  - {term}")

    if curated.get("dropped"):
        print()
        print(f"Dropped from KeyBERT bucket ({len(curated['dropped'])} phrases):")
        for p in curated["dropped"][:15]:
            print(f"  - {p}")
        if len(curated["dropped"]) > 15:
            print(f"  ... and {len(curated['dropped']) - 15} more")

    if curated.get("added_synonyms"):
        print()
        print("Added synonyms (expansions of bucket phrases):")
        for p in curated["added_synonyms"]:
            print(f"  - {p}")

    print()
    print("=" * 60)
    print()
    print("Review this vocabulary with the user. If it captures what real")
    print("papers in the field actually use, proceed to PICOC slot filling.")
    print("If something is missing or wrong, edit and re-run, or fill PICOC")
    print("slots manually using the curated set as the canonical vocabulary.")
    print()
    print("Next: PICOC slot proposal in project.yaml, then queries:")
    print(f"  python scripts/01_generate_queries.py --project {cfg.project_id}")


if __name__ == "__main__":
    main()

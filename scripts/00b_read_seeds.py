#!/usr/bin/env python3
"""Read concrete seed papers and persist their metadata.

The agent calls this after collecting up to 3 concrete seeds from the user
(DOI, OpenAlex ID, or PDF path). The script:
  1. Reads each seed (network for DOI/OpenAlex, local for PDF).
  2. Extracts title, abstract, keywords, authors, year, venue, OpenAlex
     concepts (when available), full-text excerpt (for PDFs).
  3. Persists each as projects/<id>/seeds/<seed_id>.json.
  4. Reports what was read, what was dropped (cap), what errored.

Output is consumed by litkit/vocab.py for KeyBERT + LLM vocabulary extraction.

The seeds for this script come from project.yaml's `seeds` section — the
agent should write them there before invoking this script. Supported shape:

  seeds:
    papers:
      - doi: "10.1234/example"             # or
      - openalex: "W123456789"             # or
      - pdf: "/abs/path/to/paper.pdf"      # or
      - identifier: "..."                  # auto-classified
        note: "optional human note"

Usage:
  python scripts/00b_read_seeds.py --project <slug>
  python scripts/00b_read_seeds.py --project <slug> --force  # re-read all
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.store import ProjectConfig, ProjectPaths, connect, insert_source_hit, log_event
from litkit.seeds import (
    read_seeds_batch, write_seed_records, classify_seed, SEED_CAP,
)


def _extract_seed_values(cfg: ProjectConfig) -> list[str]:
    """Walk project.yaml's seeds.papers and produce a flat list of
    seed identifiers (DOI / OpenAlex ID / PDF path)."""
    values: list[str] = []
    for paper in (cfg.seeds.get("papers") or []):
        if not isinstance(paper, dict):
            continue
        for key in ("doi", "openalex", "pdf", "identifier"):
            v = paper.get(key)
            if v:
                values.append(str(v))
                break
    return values


def _seed_authors_for_store(authors: list[str]) -> list[dict]:
    out = []
    for name in authors or []:
        parts = str(name).rsplit(" ", 1)
        if len(parts) == 2:
            given, family = parts
        else:
            given, family = "", str(name)
        out.append({"family": family, "given": given})
    return out


def _insert_seed_records(conn, records) -> int:
    inserted = 0
    for rec in records:
        if rec.error or not rec.title:
            continue
        raw = rec.to_json()
        doi = rec.raw_metadata.get("doi")
        if not doi and rec.source_kind == "doi":
            doi = rec.source_value
        openalex_id = rec.raw_metadata.get("openalex_id")
        insert_source_hit(
            conn,
            source="seed",
            source_id=rec.seed_id,
            query_id=None,
            raw=raw,
            title=rec.title,
            abstract=rec.abstract or rec.full_text_excerpt,
            authors=_seed_authors_for_store(rec.authors),
            year=rec.year,
            doi=doi,
            openalex_id=openalex_id,
            venue=rec.venue,
            keywords=rec.keywords or [c.get("name") for c in rec.concepts if c.get("name")],
            url=rec.source_value if rec.source_kind == "pdf" else None,
            from_seed=True,
        )
        inserted += 1
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--force", action="store_true",
                    help="Re-read seeds even if they're already persisted")
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)

    seeds_dir = project_dir / "seeds"

    # If seeds already exist and --force not set, skip
    if seeds_dir.exists() and any(seeds_dir.glob("seed_*.json")) and not args.force:
        existing = sorted(seeds_dir.glob("seed_*.json"))
        print(f"Seeds already read for {cfg.project_id}:")
        for p in existing:
            print(f"  {p.name}")
        print()
        print("Use --force to re-read.")
        return

    # Pull seed values from project.yaml
    seed_values = _extract_seed_values(cfg)
    if not seed_values:
        print("No seeds in project.yaml.")
        print()
        print("This engine needs at least one concrete seed paper to anchor")
        print("vocabulary derivation. Without seeds, query terms come from")
        print("general associations, which usually pulls in too much off-topic")
        print("literature.")
        print()
        print("A few ways to find one:")
        print("  - Google Scholar: search a phrase central to your topic, ")
        print("    grab the DOI of something clearly on-topic")
        print("  - arXiv: useful for working papers, especially in CS / quant fields")
        print("  - OpenAlex web interface (openalex.org): broader academic coverage")
        print("  - A colleague who works in the area, or your own past reading")
        print()
        print(f"Up to {SEED_CAP} seeds; one good one is enough to start.")
        print("DOI, OpenAlex ID, or PDF — whichever you have.")
        print()
        print(f"Add seeds to {project_dir / 'project.yaml'} under `seeds.papers`")
        print("then re-run this script.")
        sys.exit(1)

    # Pre-flight: classify each seed and surface unknowns
    classifications = [classify_seed(v) for v in seed_values]
    unknowns = [(v, c) for v, c in zip(seed_values, classifications) if c == "unknown"]
    if unknowns:
        print("Cannot classify these seeds:")
        for v, _ in unknowns:
            print(f"  {v!r}")
        print()
        print("Each seed must be one of:")
        print("  - A DOI (e.g. '10.1234/example' or 'https://doi.org/10.1234/example')")
        print("  - An OpenAlex Work ID (e.g. 'W123456789')")
        print("  - A path to a local .pdf file (must exist on disk)")
        sys.exit(1)

    # Read
    print(f"Reading {min(len(seed_values), SEED_CAP)} seed(s) for {cfg.project_id}...")
    if len(seed_values) > SEED_CAP:
        print(f"  (Soft cap: keeping first {SEED_CAP}, dropping {len(seed_values) - SEED_CAP})")
    print()

    records, dropped = read_seeds_batch(
        seed_values, contact_email=cfg.contact_email
    )

    # Write to disk
    written = write_seed_records(seeds_dir, records)

    # Audit log + ingest seeds as canonical records for v0.6 snowball start set
    with connect(paths.db) as conn:
        inserted_seed_records = _insert_seed_records(conn, records)
        log_event(
            conn, "scoping", "info",
            f"Read {len(records)} seeds, {len(dropped)} dropped",
            {"records_read": len(records), "dropped": dropped,
             "project_id": cfg.project_id,
             "seed_records_ingested": inserted_seed_records}
        )

    # Report
    print(f"Persisted {len(written)} seed records to {seeds_dir}/")
    print(f"Ingested {inserted_seed_records} seed record(s) into project.db with from_seed=1")
    print()
    for rec in records:
        if rec.error:
            print(f"  {rec.seed_id} ({rec.source_kind}): ERROR — {rec.error}")
        else:
            title_short = (rec.title or "(no title)")[:80]
            print(f"  {rec.seed_id} ({rec.source_kind}): {title_short}")
            extras = []
            if rec.authors:
                extras.append(f"{len(rec.authors)} authors")
            if rec.year:
                extras.append(f"year={rec.year}")
            if rec.keywords:
                extras.append(f"{len(rec.keywords)} keywords")
            if rec.concepts:
                extras.append(f"{len(rec.concepts)} OpenAlex concepts")
            if rec.full_text_excerpt:
                extras.append(f"{len(rec.full_text_excerpt)} chars full text")
            elif rec.abstract:
                extras.append(f"{len(rec.abstract)} chars abstract")
            if extras:
                print(f"     {' | '.join(extras)}")

    if dropped:
        print()
        print("Dropped (above soft cap):")
        for d in dropped:
            print(f"  {d}")

    # Errors blocked
    errored = [r for r in records if r.error]
    if errored:
        print()
        print(f"WARNING: {len(errored)} seed(s) had errors. Review above before")
        print("proceeding to vocabulary extraction. Consider supplying alternative")
        print("seeds for any that failed.")

    print()
    print("Next: run vocabulary extraction.")
    print(f"  python scripts/00c_extract_vocabulary.py --project {cfg.project_id}")


if __name__ == "__main__":
    main()

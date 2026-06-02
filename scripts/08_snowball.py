#!/usr/bin/env python3
"""Snowball sampling.

For every paper marked include at the latest screening pass available
(prefers full_text over title_abstract), walk its references (backward)
and citations (forward) via OpenAlex. New finds go through the same
schema as fresh search hits — they need to be screened.

Methodology:
- Default is one iteration. Multi-iteration explodes set size.
- Both directions enabled by default. --backward-only or --forward-only
  to restrict.
- --max-per-seed caps how many citations we follow per seed (forward
  snowballing on heavily-cited papers can yield thousands; default 200).

After this script runs, you do NOT have new screening labels yet — new
records sit unlabeled in the DB. Run 04_screen_prep (or 04c_llm_screen)
to screen them.

Usage:
  python scripts/08_snowball.py --project <id>
  python scripts/08_snowball.py --project <id> --backward-only
  python scripts/08_snowball.py --project <id> --max-per-seed 100
"""
import argparse
import datetime as dt
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import (
    ProjectConfig, ProjectPaths, connect, insert_source_hit, log_event,
    record_query
)
from slr_engine.snowball import snowball_seed
from slr_engine.sources.semantic_scholar import SemanticScholarAdapter


def _snowball_state(conn) -> tuple[int, int | None]:
    rows = conn.execute(
        "SELECT payload_json FROM events WHERE stage='snowball' AND payload_json IS NOT NULL"
    ).fetchall()
    max_iteration = 0
    last_included_count = None
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        iteration = int(payload.get("iteration") or 0)
        if iteration >= max_iteration:
            max_iteration = iteration
            last_included_count = payload.get("included_count")
    return max_iteration + 1, last_included_count


def _included_count(conn) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT record_id) AS n
        FROM screening
        WHERE pass='title_abstract' AND decision IN ('include', 'unsure')
        """
    ).fetchone()
    return int(row["n"] or 0)


def _seed_s2_id(conn, s2: SemanticScholarAdapter, seed) -> str | None:
    row = conn.execute(
        "SELECT source_id FROM source_hits WHERE record_id=? AND source='semantic_scholar' LIMIT 1",
        (seed["id"],),
    ).fetchone()
    if row and row["source_id"]:
        return row["source_id"]
    if seed["doi"]:
        hit = s2.lookup_by_doi(seed["doi"])
        if hit:
            return hit.get("paperId")
    return None


def _rank_from_edge(edge: dict) -> int:
    intents = {str(x).lower() for x in (edge.get("intents") or [])}
    if edge.get("isInfluential"):
        return 100
    if intents.intersection({"methodology", "extension"}):
        return 50
    if "result-comparison" in intents:
        return 25
    if "background" in intents:
        return 10
    return 5


def _doi_key(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return f"doi:{doi}" if doi else None


def _s2_rank_map(conn, cfg, seed, direction: str, enabled: bool) -> dict[str, int]:
    if not enabled:
        return {}
    s2 = SemanticScholarAdapter(contact_email=cfg.contact_email)
    s2_id = _seed_s2_id(conn, s2, seed)
    if not s2_id:
        return {}
    edge_direction = "references" if direction == "backward" else "citations"
    edges = s2.get_paper_edges(s2_id, edge_direction)
    ranks: dict[str, int] = {}
    paper_key = "citedPaper" if direction == "backward" else "citingPaper"
    for edge in edges:
        paper = edge.get(paper_key) or {}
        rank = _rank_from_edge(edge)
        if paper.get("paperId"):
            ranks[f"s2:{paper['paperId']}"] = max(ranks.get(f"s2:{paper['paperId']}", 0), rank)
        external = paper.get("externalIds") or {}
        if external.get("DOI"):
            key = _doi_key(external["DOI"])
            if key:
                ranks[key] = max(ranks.get(key, 0), rank)
    return ranks


def _rank_for_record(rec, rank_map: dict[str, int]) -> int | None:
    if not rank_map:
        return None
    ranks = []
    if rec.doi:
        ranks.append(rank_map.get(_doi_key(rec.doi)))
    if rec.source == "semantic_scholar" and rec.source_id:
        ranks.append(rank_map.get(f"s2:{rec.source_id}"))
    ranks = [r for r in ranks if r is not None]
    return max(ranks) if ranks else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--backward-only", action="store_true")
    ap.add_argument("--forward-only", action="store_true")
    ap.add_argument("--max-per-seed", type=int, default=200,
                    help="Cap on citations followed per seed (forward only)")
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)

    if args.backward_only and args.forward_only:
        print("Use either --backward-only or --forward-only, not both.")
        sys.exit(1)
    do_backward = not args.forward_only
    do_forward = not args.backward_only

    # Find the start set. v0.6 prioritizes scoping seeds, then the remaining
    # T/A include-or-unsure set, per Wohlin start-set semantics.
    with connect(paths.db) as conn:
        iteration, last_included_count = _snowball_state(conn)
        current_included_count = _included_count(conn)
        if last_included_count is not None and current_included_count <= int(last_included_count):
            log_event(
                conn, "snowball", "info",
                f"snowball iteration {iteration}: closure reached",
                {"iteration": iteration, "new_records_added": 0,
                 "included_count": current_included_count, "closure": True}
            )
            print(f"[snowball] iteration {iteration}: 0 new included records since last iteration. Closure reached.")
            print("Snowball is complete. Proceed to OA resolution (05).")
            return
        seeds = conn.execute(
            """
            SELECT r.id, r.canonical_id, r.openalex_id, r.doi, r.title, r.from_seed
            FROM records r
            JOIN screening s ON s.record_id = r.id
            WHERE s.pass = 'title_abstract'
              AND s.decision IN ('include', 'unsure')
            GROUP BY r.id
            ORDER BY COALESCE(r.from_seed, 0) DESC, r.id ASC
            """
        ).fetchall()

    if not seeds:
        print("No included records to snowball from. Run screening first.")
        return

    seed_count = sum(1 for s in seeds if s["from_seed"])
    ta_count = len(seeds) - seed_count
    s2_enabled = cfg.sources.get("semantic_scholar") is True
    print(f"[snowball] iteration {iteration}, seeds first ({seed_count} papers)")
    print(f"Snowballing from {len(seeds)} title/abstract include-or-unsure records.")
    print(f"  backward: {do_backward}  forward: {do_forward}")
    print(f"  S2 ranking: {s2_enabled}")
    print()

    query_id = f"snowball_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    new_records = 0
    new_links = 0
    links_from_seeds = 0
    links_from_ta = 0
    seeds_processed = 0
    failures = 0
    seen_non_seed_phase = False

    for seed in seeds:
        seeds_processed += 1
        if not seed["from_seed"] and not seen_non_seed_phase:
            seen_non_seed_phase = True
            print(f"[snowball] iteration {iteration}, T/A-pass records next ({ta_count} papers)")
        if not (seed["openalex_id"] or seed["doi"]):
            print(f"  [skip] {seed['canonical_id']}: no OpenAlex/DOI to walk from")
            continue

        for direction in (["backward"] if do_backward else []) + \
                         (["forward"] if do_forward else []):
            try:
                rank_map = {}
                with connect(paths.db) as conn:
                    rank_map = _s2_rank_map(conn, cfg, seed, direction, s2_enabled)
                gen = snowball_seed(
                    record_id_value=seed["openalex_id"],
                    doi=seed["doi"],
                    direction=direction,
                    contact_email=cfg.contact_email,
                )
                candidates = []
                for rec in gen:
                    candidates.append((_rank_for_record(rec, rank_map), rec))
                    if direction == "forward" and len(candidates) >= args.max_per_seed:
                        break
                candidates.sort(key=lambda x: (x[0] is None, -(x[0] or 0), x[1].title or ""))
                taken = 0
                inserted_for_seed = 0
                with connect(paths.db) as conn:
                    for rank, rec in candidates:
                        # Insert as a regular source hit; if it already exists
                        # (DOI/PMID/OpenAlex match), it gets attached to the
                        # existing record. Otherwise it's a new record.
                        new_record_id = insert_source_hit(
                            conn,
                            source=rec.source,
                            source_id=rec.source_id,
                            query_id=query_id,
                            raw=rec.raw or {},
                            title=rec.title,
                            abstract=rec.abstract,
                            authors=rec.authors,
                            year=rec.year,
                            doi=rec.doi,
                            pmid=rec.pmid,
                            pmcid=rec.pmcid,
                            openalex_id=rec.openalex_id,
                            venue=rec.venue,
                            document_type=rec.document_type,
                            language=rec.language,
                            keywords=rec.keywords,
                            url=rec.url,
                            snowball_rank=rank,
                        )
                        # Skip self-link (seed citing itself, etc.)
                        if new_record_id == seed["id"]:
                            continue
                        # Record provenance — was the record there before?
                        existed = conn.execute(
                            "SELECT 1 FROM snowball_links "
                            "WHERE seed_record_id=? AND found_record_id=? "
                            "AND direction=?",
                            (seed["id"], new_record_id, direction)
                        ).fetchone()
                        if not existed:
                            conn.execute(
                                "INSERT OR IGNORE INTO snowball_links "
                                "(seed_record_id, found_record_id, direction, iteration) "
                                "VALUES (?,?,?,?)",
                                (seed["id"], new_record_id, direction, iteration)
                            )
                            new_links += 1
                            inserted_for_seed += 1
                            if seed["from_seed"]:
                                links_from_seeds += 1
                            else:
                                links_from_ta += 1
                        taken += 1
                new_records += taken
                print(
                    f"  {'seed ' if seed['from_seed'] else ''}{seed['canonical_id']}: "
                    f"{direction} {taken} candidates, ingested {inserted_for_seed} new links"
                )
            except Exception as e:
                failures += 1
                print(f"  [error] seed {seed['canonical_id']} {direction}: {e}")
                with connect(paths.db) as conn:
                    log_event(conn, "snowball", "error", str(e),
                              {"seed_id": seed["id"], "direction": direction,
                               "trace": traceback.format_exc()[:300]})

    with connect(paths.db) as conn:
        record_query(conn, query_id, "snowball",
                     "openalex referenced_works + cited_by", None,
                     new_records,
                     notes=f"backward={do_backward} forward={do_forward} "
                           f"max_per_seed={args.max_per_seed}")
        log_event(conn, "snowball", "info",
                  f"snowball iteration {iteration} complete",
                  {"iteration": iteration, "new_records_added": new_records,
                   "new_links": new_links, "from_seeds": links_from_seeds,
                   "from_ta_pass": links_from_ta,
                   "included_count": current_included_count,
                   "seeds": len(seeds), "failures": failures})

    print()
    print("Snowball summary:")
    print(f"  seeds:       {len(seeds)}")
    print(f"  iteration:   {iteration}")
    print(f"  new links:   {new_links}")
    print(f"  ingested:    {new_records} candidate records (many may be dups)")
    print(f"  failures:    {failures}")
    print()
    print("Next: dedup, then screen the new records. Repeat snowball until closure.")
    print(f"  python scripts/03_dedup.py --project {args.project}")
    print(f"  python scripts/04_screen_prep.py --project {args.project}")
    print(f"  python scripts/04b_screen_commit.py --batch <batch_path>")
    print(f"  python scripts/08_snowball.py --project {args.project}")


if __name__ == "__main__":
    main()

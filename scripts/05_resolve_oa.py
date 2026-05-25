#!/usr/bin/env python3
"""Resolve open-access full-text URLs for included records.

Walks the resolver chain (PMC → Europe PMC → OpenAlex → Unpaywall → CORE →
Crossref) and stores the result in the downloads table with status='resolved'.
CORE is used only when `sources.core: true` in project.yaml and `CORE_API_KEY`
is set. The actual fetch happens in 06_download.py.

By default, only resolves records with screening decision='include'. Use
--all-screened to also include 'unsure'.

Usage:
  python scripts/05_resolve_oa.py --project <id>
  python scripts/05_resolve_oa.py --project <id> --decided-by agent
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.env import load_dotenv, openalex_api_key
from litkit.store import ProjectConfig, ProjectPaths, connect
from litkit.oa_resolver import resolve, ALLOWED_OA_TIERS


load_dotenv()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--all-screened", action="store_true",
                    help="Also resolve 'unsure' records")
    ap.add_argument("--decided-by", default=None,
                    help="Filter screening rows by decided_by (e.g. agent, human, llm)")
    ap.add_argument("--core-api-key", default=None)
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)

    decisions = ("include",) if not args.all_screened else ("include", "unsure")
    placeholders = ",".join("?" * len(decisions))

    screening_filter = ""
    params: list = list(decisions)
    if args.decided_by:
        screening_filter = " AND s.decided_by = ?"
        params.append(args.decided_by)

    with connect(paths.db) as conn:
        rows = conn.execute(
            f"SELECT r.id, r.canonical_id, r.doi, r.pmid, r.pmcid, r.openalex_id "
            f"FROM records r "
            f"JOIN screening s ON s.record_id = r.id "
            f"WHERE s.pass = 'title_abstract' AND s.decision IN ({placeholders})"
            f"{screening_filter} "
            f"AND r.id NOT IN ("
            f"  SELECT record_id FROM downloads "
            f"  WHERE status IN ('resolved', 'success')"
            f") "
            f"ORDER BY r.id",
            params
        ).fetchall()

    print(f"Resolving OA for {len(rows)} records...")
    resolved = 0
    skipped = 0
    tier_blocked = 0
    oa_key = openalex_api_key(cfg)
    core_key = None
    if cfg.sources.get("core") is True:
        core_key = args.core_api_key or os.environ.get("CORE_API_KEY")

    for r in rows:
        result = resolve(
            doi=r["doi"], pmid=r["pmid"], pmcid=r["pmcid"],
            openalex_id=r["openalex_id"],
            contact_email=cfg.contact_email,
            core_api_key=core_key,
            openalex_api_key=oa_key,
        )
        with connect(paths.db) as conn:
            if result is None:
                conn.execute(
                    "INSERT INTO downloads "
                    "(record_id, resolver_source, url, status) "
                    "VALUES (?, 'none', '', 'skipped_closed')",
                    (r["id"],)
                )
                conn.execute(
                    "UPDATE records SET oa_status = 'closed' WHERE id = ?",
                    (r["id"],)
                )
                skipped += 1
            else:
                oa_status = result.get("oa_status", "unknown")
                if oa_status not in ALLOWED_OA_TIERS:
                    conn.execute(
                        "INSERT INTO downloads "
                        "(record_id, resolver_source, url, status) "
                        "VALUES (?, ?, ?, 'skipped_closed')",
                        (r["id"], result["resolver_source"], result["url"])
                    )
                    conn.execute(
                        "UPDATE records SET oa_status = ?, oa_url = ? WHERE id = ?",
                        (oa_status, result["url"], r["id"])
                    )
                    tier_blocked += 1
                    continue

                conn.execute(
                    "INSERT INTO downloads "
                    "(record_id, resolver_source, url, license, file_format, status) "
                    "VALUES (?,?,?,?,?,'resolved')",
                    (r["id"], result["resolver_source"], result["url"],
                     result.get("license"), result.get("file_format"))
                )
                conn.execute(
                    "UPDATE records SET oa_status = ?, oa_url = ?, license = ? "
                    "WHERE id = ?",
                    (oa_status, result["url"], result.get("license"), r["id"])
                )
                resolved += 1

    print(f"Resolved: {resolved}")
    print(f"Skipped (no OA found): {skipped}")
    if tier_blocked:
        print(f"Skipped (OA tier not allowed): {tier_blocked}")
    print()
    print("Next: python scripts/06_download.py --project", args.project)


if __name__ == "__main__":
    main()

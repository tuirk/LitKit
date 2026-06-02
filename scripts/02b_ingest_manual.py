#!/usr/bin/env python3
"""Ingest manual Scopus / Web of Science / Google Scholar exports.

The user drops files in projects/<id>/imports/. Filename prefix determines
source: scopus_*.ris, wos_*.ris, scholar_*.ris, scopus_*.csv, wos_*.txt, etc.

Usage:
  python scripts/02b_ingest_manual.py --project <id>
"""
import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import ProjectConfig, ProjectPaths, connect, insert_source_hit, log_event, record_query
from slr_engine.importers import import_file


def _detect_source(filename: str) -> str | None:
    n = filename.lower()
    if n.startswith("scopus"):
        return "scopus"
    if n.startswith("wos") or n.startswith("web_of_science") or n.startswith("webofscience"):
        return "web_of_science"
    if n.startswith("scholar") or n.startswith("google_scholar"):
        return "google_scholar_manual"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = Path(args.projects_root) / args.project
    cfg = ProjectConfig.load(project_dir)
    paths = ProjectPaths(project_dir)
    paths.ensure()

    files = sorted(paths.imports.glob("*"))
    if not files:
        print(f"No files in {paths.imports}.")
        print("Drop Scopus/WoS/Scholar exports there with prefix scopus_, wos_, or scholar_ and re-run.")
        return

    totals = {}
    for f in files:
        if f.is_dir() or f.name.startswith("."):
            continue
        source = _detect_source(f.name)
        if not source:
            print(f"[skip] {f.name}: no source prefix (use scopus_, wos_, or scholar_)")
            continue

        query_id = f"manual_{source}_{f.stem}_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        n = 0
        try:
            with connect(paths.db) as conn:
                for rec in import_file(f, source):
                    insert_source_hit(
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
                        venue=rec.venue,
                        document_type=rec.document_type,
                        language=rec.language,
                        keywords=rec.keywords,
                        url=rec.url,
                    )
                    n += 1
                record_query(conn, query_id, source,
                             f"<manual import: {f.name}>", None, n,
                             notes=str(f))
                log_event(conn, "ingest", "info",
                          f"Imported {n} records from {f.name}",
                          {"source": source, "file": str(f)})
        except Exception as e:
            print(f"[error] {f.name}: {e}\n{traceback.format_exc()}")
            with connect(paths.db) as conn:
                log_event(conn, "ingest", "error", str(e),
                          {"file": str(f), "source": source})
        else:
            totals[f.name] = (source, n)
            print(f"[done] {f.name} ({source}): {n} records")

    print()
    print("Summary:")
    for fname, (src, n) in totals.items():
        print(f"  {fname}: {src} → {n}")
    print()
    print("Next: python scripts/03_dedup.py --project", args.project)


if __name__ == "__main__":
    main()

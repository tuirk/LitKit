#!/usr/bin/env python3
"""Download OA full-text files for resolved records.

Reads downloads with status='resolved', fetches each, writes to
projects/<id>/data/fulltext/, updates status to 'success' or 'failed'.

Idempotent: skips downloads with status='success' that have a valid file.

Usage:
  python scripts/06_download.py --project <id>
  python scripts/06_download.py --project <id> --max 50
"""
import argparse
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.store import ProjectPaths, connect, log_event
from litkit.oa_resolver import ALLOWED_OA_TIERS


USER_AGENT = "litkit/1.0 (research; OA only)"


def _safe_filename(canonical_id: str, fmt: str) -> str:
    ext = {"pdf": "pdf", "xml": "xml", "html": "html"}.get(fmt, "bin")
    return f"{canonical_id}.{ext}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max", type=int, default=10000)
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Seconds between requests (be polite)")
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    paths = ProjectPaths(Path(args.projects_root) / args.project)
    paths.fulltext.mkdir(parents=True, exist_ok=True)

    with connect(paths.db) as conn:
        rows = conn.execute(
            "SELECT d.id AS dl_id, d.record_id, d.url, d.file_format, "
            "       r.canonical_id, r.oa_status "
            "FROM downloads d "
            "JOIN records r ON r.id = d.record_id "
            "JOIN ("
            "  SELECT record_id, MAX(id) AS max_id "
            "  FROM downloads "
            "  WHERE status = 'resolved' "
            "  GROUP BY record_id"
            ") latest ON latest.max_id = d.id "
            "ORDER BY d.id LIMIT ?",
            (args.max,)
        ).fetchall()

    print(f"Downloading {len(rows)} files...")
    ok = failed = skipped = 0
    for r in rows:
        oa_status = (r["oa_status"] or "unknown").lower()
        if oa_status not in ALLOWED_OA_TIERS:
            with connect(paths.db) as conn:
                conn.execute(
                    "UPDATE downloads SET status='skipped_closed', "
                    "error=? WHERE id=?",
                    (f"oa_status={oa_status} not in allowed tiers", r["dl_id"])
                )
                log_event(conn, "download", "info",
                          f"Skipped non-OA tier: {r['canonical_id']}",
                          {"oa_status": oa_status})
            skipped += 1
            print(f"  SKIP {r['canonical_id']} (oa_status={oa_status})")
            continue

        fname = _safe_filename(r["canonical_id"], r["file_format"] or "bin")
        out_path = paths.fulltext / fname
        try:
            req = urllib.request.Request(
                r["url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            out_path.write_bytes(data)
            with connect(paths.db) as conn:
                conn.execute(
                    "UPDATE downloads SET status='success', file_path=? WHERE id=?",
                    (str(out_path.relative_to(paths.root)), r["dl_id"])
                )
            ok += 1
            print(f"  OK {fname} ({len(data)//1024} KB)")
        except Exception as e:
            with connect(paths.db) as conn:
                conn.execute(
                    "UPDATE downloads SET status='failed', error=? WHERE id=?",
                    (str(e)[:500], r["dl_id"])
                )
                log_event(conn, "download", "warn",
                          f"Failed: {r['canonical_id']}",
                          {"url": r["url"], "error": str(e)})
            failed += 1
            print(f"  FAIL {fname}: {e}")
        time.sleep(args.sleep)

    print()
    print(f"Success: {ok}")
    print(f"Failed:  {failed}")
    if skipped:
        print(f"Skipped (non-OA tier): {skipped}")
    print()
    print("Next: python scripts/07_fulltext_prep.py --project", args.project,
          "(or scripts/09_export.py if skipping full-text pass)")


if __name__ == "__main__":
    main()

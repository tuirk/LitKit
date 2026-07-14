#!/usr/bin/env python3
"""Download OA full-text files for resolved records.

Walks status='resolved' then status='queued' candidates per record until one
download succeeds. Leftover queued rows become skipped_superseded.

Usage:
  python scripts/06_download.py --project <id>
  python scripts/06_download.py --project <id> --max 50
  python scripts/06_download.py --project <id> --retry-failed
"""
import argparse
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slr_engine.store import ProjectPaths, connect, log_event
from slr_engine.oa_resolver import ALLOWED_OA_TIERS
from slr_engine.not_downloaded import (
    fetch_not_downloaded,
    rows_to_dicts,
    write_not_downloaded_report,
)


USER_AGENT = "slr-engine/1.0 (research; OA only)"


def _safe_filename(canonical_id: str, fmt: str) -> str:
    ext = {"pdf": "pdf", "xml": "xml", "html": "html"}.get(fmt, "bin")
    return f"{canonical_id}.{ext}"


def _looks_like_pdf(data: bytes, file_format: str | None) -> bool:
    if (file_format or "").lower() != "pdf":
        return True
    return data[:5] == b"%PDF-" or data[:4] == b"%PDF"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max", type=int, default=10000,
                    help="Max records (not URLs) to attempt")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Seconds between requests (be polite)")
    ap.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-queue records that only have failed attempts (promote to resolved)",
    )
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    paths = ProjectPaths(Path(args.projects_root) / args.project)
    paths.fulltext.mkdir(parents=True, exist_ok=True)
    paths.screening.mkdir(parents=True, exist_ok=True)

    with connect(paths.db) as conn:
        if args.retry_failed:
            # Promote latest failed row per record (no success) back to resolved
            # and clear sibling failed/queued so 05 can also be re-run cleanly.
            failed_ids = [
                r["record_id"]
                for r in conn.execute(
                    """
                    SELECT DISTINCT d.record_id
                    FROM downloads d
                    WHERE d.status = 'failed'
                      AND d.record_id NOT IN (
                        SELECT record_id FROM downloads WHERE status = 'success'
                      )
                    """
                ).fetchall()
            ]
            for rid in failed_ids:
                # Keep URLs: set all failed/queued/skipped_superseded → queued,
                # then first by id → resolved
                conn.execute(
                    """
                    UPDATE downloads SET status='queued', error=NULL
                    WHERE record_id=? AND status IN
                      ('failed', 'queued', 'skipped_superseded', 'resolved')
                    """,
                    (rid,),
                )
                first = conn.execute(
                    "SELECT id FROM downloads WHERE record_id=? "
                    "AND status='queued' ORDER BY id LIMIT 1",
                    (rid,),
                ).fetchone()
                if first:
                    conn.execute(
                        "UPDATE downloads SET status='resolved' WHERE id=?",
                        (first["id"],),
                    )
            print(f"Re-queued {len(failed_ids)} failed record(s).")

        record_ids = [
            r["record_id"]
            for r in conn.execute(
                """
                SELECT DISTINCT d.record_id
                FROM downloads d
                WHERE d.status IN ('resolved', 'queued')
                  AND d.record_id NOT IN (
                    SELECT record_id FROM downloads WHERE status = 'success'
                  )
                ORDER BY d.record_id
                LIMIT ?
                """,
                (args.max,),
            ).fetchall()
        ]

    print(f"Downloading for {len(record_ids)} records...")
    ok = failed = skipped = 0

    for record_id in record_ids:
        with connect(paths.db) as conn:
            meta = conn.execute(
                "SELECT canonical_id, oa_status FROM records WHERE id=?",
                (record_id,),
            ).fetchone()
            candidates = conn.execute(
                """
                SELECT id AS dl_id, url, file_format, resolver_source, status
                FROM downloads
                WHERE record_id=? AND status IN ('resolved', 'queued')
                ORDER BY CASE status WHEN 'resolved' THEN 0 ELSE 1 END, id
                """,
                (record_id,),
            ).fetchall()

        if not meta or not candidates:
            continue

        oa_status = (meta["oa_status"] or "unknown").lower()
        # arXiv/green candidates are always allowed; only skip closed/hybrid records
        # when there is no candidate that carries an allowed tier via resolve time.
        if oa_status not in ALLOWED_OA_TIERS and oa_status not in ("unknown",):
            with connect(paths.db) as conn:
                for c in candidates:
                    conn.execute(
                        "UPDATE downloads SET status='skipped_closed', "
                        "error=? WHERE id=?",
                        (f"oa_status={oa_status} not in allowed tiers", c["dl_id"]),
                    )
                log_event(conn, "download", "info",
                          f"Skipped non-OA tier: {meta['canonical_id']}",
                          {"oa_status": oa_status})
            skipped += 1
            print(f"  SKIP {meta['canonical_id']} (oa_status={oa_status})")
            continue

        succeeded = False
        last_err = None
        for c in candidates:
            fname = _safe_filename(meta["canonical_id"], c["file_format"] or "bin")
            out_path = paths.fulltext / fname
            try:
                req = urllib.request.Request(
                    c["url"], headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                if not data:
                    raise ValueError("empty response body")
                if not _looks_like_pdf(data, c["file_format"]):
                    raise ValueError("response was not a PDF")
                out_path.write_bytes(data)
                with connect(paths.db) as conn:
                    conn.execute(
                        "UPDATE downloads SET status='success', file_path=?, "
                        "error=NULL WHERE id=?",
                        (str(out_path.relative_to(paths.root)), c["dl_id"]),
                    )
                    # Cancel leftover candidates for this record
                    conn.execute(
                        """
                        UPDATE downloads SET status='skipped_superseded',
                               error='superseded by successful download'
                        WHERE record_id=? AND id!=? AND status IN ('resolved', 'queued')
                        """,
                        (record_id, c["dl_id"]),
                    )
                ok += 1
                print(
                    f"  OK {fname} via {c['resolver_source']} "
                    f"({len(data)//1024} KB)"
                )
                succeeded = True
                break
            except Exception as e:
                last_err = e
                with connect(paths.db) as conn:
                    conn.execute(
                        "UPDATE downloads SET status='failed', error=? WHERE id=?",
                        (str(e)[:500], c["dl_id"]),
                    )
                    log_event(conn, "download", "warn",
                              f"Failed: {meta['canonical_id']}",
                              {"url": c["url"], "resolver_source": c["resolver_source"],
                               "error": str(e)})
                print(
                    f"  FAIL {meta['canonical_id']} via {c['resolver_source']}: {e}"
                )
            time.sleep(args.sleep)

        if not succeeded:
            failed += 1
            if last_err is None:
                print(f"  FAIL {meta['canonical_id']}: no candidates")

        if succeeded:
            time.sleep(args.sleep)

    print()
    print(f"Success: {ok}")
    print(f"Failed (all candidates):  {failed}")
    if skipped:
        print(f"Skipped (non-OA tier): {skipped}")

    # Refresh structured ILL report after the pass
    with connect(paths.db) as conn:
        nd_rows = rows_to_dicts(fetch_not_downloaded(conn))
    if nd_rows:
        csv_path, txt_path = write_not_downloaded_report(paths.screening, nd_rows)
        print(f"Not downloaded: {len(nd_rows)} — see {csv_path.name} / {txt_path.name}")

    print()
    print("Next: python scripts/07_fulltext_prep.py --project", args.project,
          "(or scripts/09_export.py if skipping full-text pass)")


if __name__ == "__main__":
    main()

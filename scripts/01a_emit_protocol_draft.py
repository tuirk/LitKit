#!/usr/bin/env python3
"""Emit the optional prospective protocol draft.

Reads project scoping state and query artifacts, writes
projects/<id>/protocol_draft.md, and logs that the draft was regenerated.

Usage:
  python scripts/01a_emit_protocol_draft.py --project <id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.protocol import write_protocol_draft
from litkit.store import ProjectConfig, ProjectPaths, connect, log_event


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

    draft_path = write_protocol_draft(cfg, paths)

    with connect(paths.db) as conn:
        log_event(
            conn,
            "scoping",
            "info",
            "protocol_draft_emitted",
            {
                "project_id": cfg.project_id,
                "path": str(draft_path.relative_to(project_dir)),
            },
        )

    print(f"Wrote: {draft_path}")


if __name__ == "__main__":
    main()

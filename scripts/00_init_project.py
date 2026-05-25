#!/usr/bin/env python3
"""Initialize a new SLR project folder.

Usage:
  python scripts/00_init_project.py --id <slug> --topic "..."

The `--topic` is the subject area in plain English. The agent will help
sharpen it into research questions during the scoping conversation
(stage 01). For backward compatibility, `--question` is still accepted
and treated as the topic.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from litkit.store import init_project


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="Project id, e.g. 'sleep_rcts_2025'")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic", help="Subject area in plain English")
    g.add_argument("--question", help="(Legacy) — same as --topic for backward compat")
    ap.add_argument(
        "--projects-root",
        default=str(Path(__file__).resolve().parents[1] / "projects"),
    )
    args = ap.parse_args()

    project_dir = init_project(
        Path(args.projects_root),
        args.id,
        topic=args.topic or "",
        question=args.question,
    )
    print(f"Created project: {project_dir}")
    print()
    print("Next: have the agent walk you through the scoping conversation.")
    print("It will sharpen the topic into research questions, structure them")
    print("via PICOC (or another framework you describe), and decide on")
    print("hypotheses, eligibility criteria, and seed papers.")
    print()
    print(f"  python scripts/01_generate_queries.py --project {args.id}")


if __name__ == "__main__":
    main()

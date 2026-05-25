# LitKit demo project

Minimal end-to-end example for verifying a LitKit install. Uses IT/LLM code-review queries with a small date window.

## Quick verify

From repo root (with venv active and deps installed):

```bash
python scripts/smoke_verify.py
```

Or run stages manually:

```bash
python scripts/00_init_project.py --project _demo   # skip if project.db exists
python scripts/02_search_open.py --project _demo --max-records 10
python scripts/03_dedup.py --project _demo
python scripts/05_resolve_oa.py --project _demo
python scripts/09_export.py --project _demo
```

## What is committed

- `project.yaml` — scoping config
- `queries/` — filled Boolean templates
- `seeds/seed_001.json` — one seed paper

Runtime artifacts (`project.db`, `exports/`, `logs/`, screening batches) stay gitignored.

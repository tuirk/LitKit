"""Small .env loader for local API keys.

The engine avoids a python-dotenv dependency. Scripts import `load_dotenv()`
before reading API keys from `os.environ`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

LITKIT_USER_AGENT = "litkit/1.0 (research; OA only)"

if TYPE_CHECKING:
    from .store import ProjectConfig


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from `.env` without overwriting real env vars."""
    env_path = path or Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def openalex_api_key(cfg: "ProjectConfig") -> Optional[str]:
    return cfg.openalex_api_key or os.environ.get("OPENALEX_API_KEY")


def pubmed_api_key(cfg: "ProjectConfig") -> Optional[str]:
    return cfg.pubmed_api_key or os.environ.get("NCBI_API_KEY")


def openalex_require_abstract(cfg: "ProjectConfig") -> bool:
    src = cfg.sources.get("openalex") if isinstance(cfg.sources, dict) else None
    if isinstance(src, dict):
        return bool(src.get("require_abstract", True))
    return True

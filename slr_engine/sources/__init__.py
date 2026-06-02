"""Base class for source adapters.

A source adapter is a thin layer over one bibliographic database. It:
1. Builds a request from a query string + filters
2. Paginates through results
3. Yields normalized record dicts

The adapter does NOT write to the DB. The orchestrating script does.
This keeps adapters testable in isolation.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class NormalizedRecord:
    source: str
    source_id: str
    title: str
    abstract: Optional[str]
    authors: list[dict]              # [{"family": "...", "given": "..."}, ...]
    year: Optional[int]
    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    openalex_id: Optional[str] = None
    venue: Optional[str] = None
    document_type: Optional[str] = None
    language: Optional[str] = None
    keywords: Optional[list[str]] = None
    url: Optional[str] = None
    tldr: Optional[str] = None
    snowball_rank: Optional[int] = None
    raw: Optional[dict] = None


class SourceAdapter(ABC):
    name: str = "base"

    def __init__(self, contact_email: Optional[str] = None,
                 user_agent: str = "slr-engine/1.0 (research; OA only)"):
        self.contact_email = contact_email
        self.user_agent = user_agent
        # Tracks whether any HTTP request in this adapter's lifetime errored.
        # The orchestrating script reads this AFTER iteration completes to
        # distinguish a real null result ("0 records, no errors") from a
        # silent failure ("0 records, but 4 requests errored along the way").
        self._errors_during_run: list[str] = []

    @abstractmethod
    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        languages: Optional[list[str]] = None,
        max_records: int = 1000,
    ) -> Iterator[NormalizedRecord]:
        """Yield normalized records for a query."""
        ...

    def _polite_sleep(self, seconds: float = 0.1) -> None:
        time.sleep(seconds)

    def _record_error(self, msg: str) -> None:
        """Adapters call this when an HTTP request fails. The orchestrator
        reads `errors_during_run` after iteration to detect silent failures."""
        self._errors_during_run.append(msg)

    @property
    def errors_during_run(self) -> list[str]:
        """List of error messages from this adapter's HTTP attempts.
        Empty list = clean run."""
        return list(self._errors_during_run)

    def reset_errors(self) -> None:
        """Call before reusing the adapter for a new search."""
        self._errors_during_run = []


# ---------- module registry ----------

def get_adapter(name: str, contact_email: Optional[str] = None, **kwargs) -> SourceAdapter:
    """Return an adapter instance by name."""
    from . import openalex, crossref, pubmed, europepmc, arxiv
    from . import semantic_scholar, dblp, ia_scholar

    if name == "openalex":
        return openalex.OpenAlexAdapter(
            contact_email=contact_email,
            api_key=kwargs.get("openalex_api_key"),
            require_abstract=kwargs.get("require_abstract", True),
        )
    if name == "pubmed":
        return pubmed.PubMedAdapter(
            contact_email=contact_email,
            api_key=kwargs.get("pubmed_api_key"),
        )

    registry = {
        "crossref": crossref.CrossrefAdapter,
        "europe_pmc": europepmc.EuropePMCAdapter,
        "arxiv": arxiv.ArxivAdapter,
        "semantic_scholar": semantic_scholar.SemanticScholarAdapter,
        "dblp": dblp.DBLPAdapter,
        "ia_scholar": ia_scholar.IAScholarAdapter,
    }
    cls = registry.get(name)
    if cls is None:
        raise ValueError(f"Unknown adapter: {name}")
    return cls(contact_email=contact_email)

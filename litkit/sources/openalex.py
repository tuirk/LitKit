"""OpenAlex adapter.

Docs:
- https://docs.openalex.org/api-entities/works/search-works
- https://docs.openalex.org/api-entities/works/filter-works
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Iterator, Optional

from . import SourceAdapter, NormalizedRecord

# OpenAlex rejects URLs whose query string exceeds ~4096 chars. Long Boolean
# queries must be split into chunks and merged client-side.
_MAX_QUERY_CHARS = 3800


def _reconstruct_abstract(inverted: Optional[dict]) -> Optional[str]:
    """OpenAlex returns abstracts as inverted indices for licensing reasons."""
    if not inverted:
        return None
    positions = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


def _split_query(query: str, max_chars: int = _MAX_QUERY_CHARS) -> list[str]:
    """Split a long Boolean query into chunks that fit OpenAlex URL limits."""
    q = query.strip()
    if len(q) <= max_chars:
        return [q]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for part in q.replace("\n", " ").split():
        add_len = len(part) + (1 if current else 0)
        if current and current_len + add_len > max_chars:
            chunks.append(" ".join(current))
            current = [part]
            current_len = len(part)
        else:
            current.append(part)
            current_len += add_len
    if current:
        chunks.append(" ".join(current))
    return chunks or [q]


class OpenAlexAdapter(SourceAdapter):
    name = "openalex"
    base = "https://api.openalex.org/works"

    def __init__(
        self,
        contact_email: Optional[str] = None,
        api_key: Optional[str] = None,
        require_abstract: bool = True,
        user_agent: str = "litkit/1.0 (research; OA only)",
    ):
        super().__init__(contact_email=contact_email, user_agent=user_agent)
        self.api_key = api_key
        self.require_abstract = require_abstract

    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        languages: Optional[list[str]] = None,
        max_records: int = 1000,
    ) -> Iterator[NormalizedRecord]:
        seen: set[str] = set()
        fetched = 0
        for chunk in _split_query(query):
            for rec in self._search_chunk(
                chunk,
                date_from=date_from,
                date_to=date_to,
                languages=languages,
                max_records=max_records - fetched,
            ):
                if rec.source_id in seen:
                    continue
                seen.add(rec.source_id)
                yield rec
                fetched += 1
                if fetched >= max_records:
                    return

    def _search_chunk(
        self,
        query: str,
        *,
        date_from: Optional[str],
        date_to: Optional[str],
        languages: Optional[list[str]],
        max_records: int,
    ) -> Iterator[NormalizedRecord]:
        filters = []
        if date_from:
            filters.append(f"from_publication_date:{date_from}")
        if date_to:
            filters.append(f"to_publication_date:{date_to}")
        if languages:
            filters.append(f"language:{'|'.join(languages)}")
        if self.require_abstract:
            filters.append("has_abstract:true")

        params = {
            "search": query,
            "filter": ",".join(filters) if filters else None,
            "per-page": "200",
            "cursor": "*",
        }
        if self.contact_email:
            params["mailto"] = self.contact_email
        params = {k: v for k, v in params.items() if v is not None}

        fetched = 0
        while True:
            url = f"{self.base}?{urllib.parse.urlencode(params)}"
            headers = {"User-Agent": self.user_agent}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
            except Exception as e:
                self._record_error(
                    f"openalex request failed: {type(e).__name__}: {e} "
                    f"(url={url[:200]})"
                )
                return

            for work in data.get("results", []):
                yield self._to_record(work)
                fetched += 1
                if fetched >= max_records:
                    return

            next_cursor = data.get("meta", {}).get("next_cursor")
            if not next_cursor or not data.get("results"):
                return
            params["cursor"] = next_cursor
            self._polite_sleep(0.1)

    def _to_record(self, w: dict) -> NormalizedRecord:
        authors = []
        for a in w.get("authorships", []):
            au = a.get("author", {}) or {}
            name = au.get("display_name") or ""
            parts = name.rsplit(" ", 1)
            given = parts[0] if len(parts) == 2 else ""
            family = parts[-1]
            authors.append({"family": family, "given": given})

        ids = w.get("ids", {}) or {}
        pmid = None
        if ids.get("pmid"):
            pmid = ids["pmid"].rsplit("/", 1)[-1]
        pmcid = None
        if ids.get("pmcid"):
            pmcid = ids["pmcid"].rsplit("/", 1)[-1]

        venue = None
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        if src.get("display_name"):
            venue = src["display_name"]

        keywords = [
            k.get("display_name")
            for k in (w.get("keywords") or [])
            if k.get("display_name")
        ]

        return NormalizedRecord(
            source="openalex",
            source_id=w.get("id", "").rsplit("/", 1)[-1],
            title=w.get("title") or w.get("display_name") or "",
            abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
            authors=authors,
            year=w.get("publication_year"),
            doi=w.get("doi"),
            pmid=pmid,
            pmcid=pmcid,
            openalex_id=ids.get("openalex"),
            venue=venue,
            document_type=w.get("type"),
            language=w.get("language"),
            keywords=keywords or None,
            url=w.get("doi") or (loc.get("landing_page_url")),
            raw=w,
        )

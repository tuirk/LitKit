"""Seed paper reader.

Reads up to 3 concrete seed papers (DOI, OpenAlex ID, or PDF path) and
extracts title + abstract + keywords + author-supplied terms + auto-tagged
concepts. The output feeds vocabulary extraction (slr_engine/vocab.py).

Soft cap at 3 seeds. If the user supplies more, the agent should drop the
extras with friction (log to events, tell user). This module enforces
the cap if called with >3 seeds.

NO discovery search. If the user has no seeds, the agent should not call
this — it should ask the user for at least one concrete seed.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from .pdf_text import extract_text as _pdf_extract


SEED_CAP = 3


@dataclass
class SeedRecord:
    """Normalized seed paper metadata, ready for vocabulary extraction."""
    seed_id: str               # e.g. "seed_001"
    source_kind: str           # 'doi' | 'openalex' | 'pdf'
    source_value: str          # the DOI / OpenAlex ID / PDF path as given
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    keywords: list[str] = field(default_factory=list)        # author-supplied
    concepts: list[dict] = field(default_factory=list)        # OpenAlex auto-tagged
    full_text_excerpt: Optional[str] = None                   # for PDFs
    raw_metadata: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, obj: dict) -> "SeedRecord":
        return cls(**obj)


class SeedError(Exception):
    pass


# ---------------------------------------------------------------------
# Identifier normalization
# ---------------------------------------------------------------------

_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
_OPENALEX_RE = re.compile(r"^W\d{6,12}$", re.IGNORECASE)


def classify_seed(value: str) -> str:
    """Return 'doi' | 'openalex' | 'pdf' | 'unknown'."""
    s = value.strip()
    if not s:
        return "unknown"
    # PDF path?
    if s.lower().endswith(".pdf") and Path(s).exists():
        return "pdf"
    # DOI variants
    s_doi = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi.org/"):
        if s_doi.startswith(prefix):
            s_doi = s_doi[len(prefix):]
    if _DOI_RE.match(s_doi):
        return "doi"
    # OpenAlex ID
    s_oa = s.split("/")[-1].upper() if "/" in s else s.upper()
    if _OPENALEX_RE.match(s_oa):
        return "openalex"
    return "unknown"


def normalize_doi(value: str) -> str:
    s = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi.org/"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def normalize_openalex_id(value: str) -> str:
    s = value.strip()
    if "/" in s:
        s = s.split("/")[-1]
    return s.upper()


# ---------------------------------------------------------------------
# Seed readers
# ---------------------------------------------------------------------

def read_seed(source_value: str, seed_id: str,
              contact_email: Optional[str] = None,
              timeout: int = 30) -> SeedRecord:
    """Read a single seed by DOI, OpenAlex ID, or PDF path."""
    kind = classify_seed(source_value)
    if kind == "doi":
        return _read_doi(source_value, seed_id, contact_email, timeout)
    if kind == "openalex":
        return _read_openalex_id(source_value, seed_id, contact_email, timeout)
    if kind == "pdf":
        return _read_pdf(source_value, seed_id)
    return SeedRecord(
        seed_id=seed_id, source_kind="unknown", source_value=source_value,
        error=f"Could not classify seed: {source_value!r}. "
              "Expected DOI, OpenAlex ID (W...), or path to .pdf file."
    )


def _read_openalex_id(value: str, seed_id: str,
                      contact_email: Optional[str], timeout: int) -> SeedRecord:
    """Fetch from OpenAlex by W-id."""
    oa_id = normalize_openalex_id(value)
    url = f"https://api.openalex.org/works/{oa_id}"
    if contact_email:
        url = f"{url}?mailto={urllib.parse.quote(contact_email)}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "slr-engine/1.0 (research; OA only)"}),
            timeout=timeout,
        ) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return SeedRecord(
            seed_id=seed_id, source_kind="openalex", source_value=value,
            error=f"OpenAlex fetch failed: {type(e).__name__}: {e}",
        )
    return _parse_openalex_record(data, seed_id, value)


def _read_doi(value: str, seed_id: str,
              contact_email: Optional[str], timeout: int) -> SeedRecord:
    """Look up DOI via OpenAlex first (richer metadata + concepts),
    fall back to Crossref if that fails."""
    doi = normalize_doi(value)
    # Try OpenAlex first (their /works/doi:... endpoint)
    oa_url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}"
    if contact_email:
        oa_url = f"{oa_url}?mailto={urllib.parse.quote(contact_email)}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(oa_url, headers={"User-Agent": "slr-engine/1.0 (research; OA only)"}),
            timeout=timeout,
        ) as resp:
            data = json.loads(resp.read())
        rec = _parse_openalex_record(data, seed_id, value)
        if rec.title and not rec.error:
            return rec
    except Exception:
        # OpenAlex didn't have it; fall through to Crossref
        pass
    # Crossref fallback (strict DOI lookup, not search; no relevance ranking)
    cr_url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    headers = {"User-Agent": "slr-engine/1.0 (research; OA only)"}
    if contact_email:
        cr_url = f"{cr_url}?mailto={urllib.parse.quote(contact_email)}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(cr_url, headers=headers), timeout=timeout
        ) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return SeedRecord(
            seed_id=seed_id, source_kind="doi", source_value=value,
            error=f"DOI lookup failed on both OpenAlex and Crossref: "
                  f"{type(e).__name__}: {e}",
        )
    return _parse_crossref_record(data.get("message", {}), seed_id, value)


def _read_pdf(value: str, seed_id: str) -> SeedRecord:
    """Extract text from a local PDF."""
    pdf_path = Path(value).resolve()
    if not pdf_path.exists():
        return SeedRecord(
            seed_id=seed_id, source_kind="pdf", source_value=value,
            error=f"PDF not found: {pdf_path}",
        )
    text = _pdf_extract(pdf_path, max_chars=20000)
    if not text:
        return SeedRecord(
            seed_id=seed_id, source_kind="pdf", source_value=value,
            error=(
                f"Could not extract text from {pdf_path.name}. "
                "May be a scanned image (no text layer). The engine does "
                "not OCR. Please supply a different seed paper or a "
                "text-bearing PDF."
            ),
        )
    # Try to extract a title and abstract heuristically from the first page-ish.
    title, abstract = _heuristic_title_abstract(text)
    return SeedRecord(
        seed_id=seed_id, source_kind="pdf", source_value=str(pdf_path),
        title=title, abstract=abstract, full_text_excerpt=text,
    )


# ---------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------

def _parse_openalex_record(data: dict, seed_id: str,
                           source_value: str) -> SeedRecord:
    """Pull what we need from an OpenAlex /works response."""
    if not data or "title" not in data:
        return SeedRecord(
            seed_id=seed_id, source_kind="openalex", source_value=source_value,
            error="OpenAlex returned empty or malformed record",
        )
    title = data.get("title") or ""
    abstract = _reconstruct_abstract_from_inverted_index(
        data.get("abstract_inverted_index")
    )
    authors = []
    for a in (data.get("authorships") or []):
        au = a.get("author") or {}
        if au.get("display_name"):
            authors.append(au["display_name"])
    year = data.get("publication_year")
    venue = (data.get("primary_location") or {}).get("source", {}).get("display_name")
    keywords = data.get("keywords") or []
    if keywords and isinstance(keywords[0], dict):
        keywords = [k.get("display_name") or k.get("keyword", "") for k in keywords]
    concepts = []
    for c in (data.get("concepts") or [])[:15]:  # top 15 by score
        concepts.append({
            "name": c.get("display_name", ""),
            "score": c.get("score", 0.0),
            "level": c.get("level", 0),
        })
    return SeedRecord(
        seed_id=seed_id, source_kind="openalex", source_value=source_value,
        title=title, abstract=abstract, authors=authors, year=year,
        venue=venue, keywords=[k for k in keywords if k], concepts=concepts,
        raw_metadata={"openalex_id": data.get("id"),
                      "doi": data.get("doi")},
    )


def _reconstruct_abstract_from_inverted_index(idx: Optional[dict]) -> str:
    """OpenAlex stores abstracts as inverted indices (word -> [positions]).
    Reconstruct the plain text."""
    if not idx:
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in idx.items():
        for p in positions:
            positioned.append((p, word))
    positioned.sort()
    return " ".join(w for _, w in positioned)


def _parse_crossref_record(msg: dict, seed_id: str,
                           source_value: str) -> SeedRecord:
    """Pull what we need from a Crossref /works/{doi} response."""
    if not msg:
        return SeedRecord(
            seed_id=seed_id, source_kind="doi", source_value=source_value,
            error="Crossref returned empty response",
        )
    title_arr = msg.get("title") or []
    title = title_arr[0] if title_arr else ""
    abstract = msg.get("abstract") or ""
    # Crossref abstracts often have JATS XML tags; strip them
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = " ".join(abstract.split())
    authors = []
    for a in (msg.get("author") or []):
        name = " ".join(filter(None, [a.get("given"), a.get("family")]))
        if name:
            authors.append(name)
    year = None
    for date_key in ("published-print", "published-online", "issued", "created"):
        d = (msg.get(date_key) or {}).get("date-parts") or []
        if d and d[0] and d[0][0]:
            year = d[0][0]
            break
    venue_arr = msg.get("container-title") or []
    venue = venue_arr[0] if venue_arr else None
    # Crossref subject = controlled vocabulary; treat as keywords
    keywords = msg.get("subject") or []
    return SeedRecord(
        seed_id=seed_id, source_kind="doi", source_value=source_value,
        title=title, abstract=abstract, authors=authors, year=year,
        venue=venue, keywords=keywords,
        raw_metadata={"doi": msg.get("DOI")},
    )


def _heuristic_title_abstract(text: str) -> tuple[str, str]:
    """Best-effort title and abstract extraction from PDF plain text.
    Title is the first non-trivial line. Abstract is the chunk between
    'abstract' and the next major heading (intro/keywords)."""
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    title = ""
    for ln in lines[:30]:
        # Skip running heads, page numbers, single chars
        if len(ln) > 15 and not ln.isdigit():
            title = ln
            break
    # Abstract heuristic
    abstract = ""
    lower = text.lower()
    abs_marker = lower.find("abstract")
    if abs_marker >= 0:
        # Find the next major heading
        end = len(text)
        for marker in ("\nintroduction", "\n1. introduction",
                       "\nkeywords", "\nkey words", "\n1 introduction"):
            pos = lower.find(marker, abs_marker)
            if pos > 0 and pos < end:
                end = pos
        chunk = text[abs_marker + len("abstract"):end]
        # Strip leading punctuation/whitespace
        chunk = chunk.lstrip(":.- \n\t")
        abstract = " ".join(chunk.split())[:3000]
    return title, abstract


# ---------------------------------------------------------------------
# Seed batch reading
# ---------------------------------------------------------------------

def read_seeds_batch(seeds: list[str], contact_email: Optional[str] = None,
                     timeout: int = 30) -> tuple[list[SeedRecord], list[str]]:
    """Read up to SEED_CAP seeds. Returns (records, dropped_with_reason).

    If more than SEED_CAP seeds supplied, the extras are dropped with
    a 'vocabulary saturation' reason.
    """
    dropped_msgs: list[str] = []
    if len(seeds) > SEED_CAP:
        for extra in seeds[SEED_CAP:]:
            dropped_msgs.append(
                f"{extra}: dropped (soft cap of {SEED_CAP} seeds — "
                "additional seeds add noise without distinctiveness gain)"
            )
        seeds = seeds[:SEED_CAP]

    records: list[SeedRecord] = []
    for i, seed_value in enumerate(seeds, 1):
        seed_id = f"seed_{i:03d}"
        rec = read_seed(seed_value, seed_id, contact_email, timeout)
        records.append(rec)

    return records, dropped_msgs


def write_seed_records(seeds_dir: Path, records: list[SeedRecord]) -> list[Path]:
    """Persist seed records to projects/<id>/seeds/<seed_id>.json. Returns
    the list of written paths."""
    seeds_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for rec in records:
        path = seeds_dir / f"{rec.seed_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec.to_json(), f, indent=2, ensure_ascii=False)
        paths.append(path)
    return paths


def load_seed_records(seeds_dir: Path) -> list[SeedRecord]:
    """Load all written seed records from projects/<id>/seeds/."""
    if not seeds_dir.exists():
        return []
    records = []
    for p in sorted(seeds_dir.glob("seed_*.json")):
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
        records.append(SeedRecord.from_json(obj))
    return records

"""Importer for manual exports from Scopus and Web of Science.

Supports RIS and CSV. The function detects format by extension.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterator

from .sources import NormalizedRecord


def import_file(path: Path, source_hint: str) -> Iterator[NormalizedRecord]:
    """source_hint: 'scopus' or 'web_of_science' — used as the source label."""
    suffix = path.suffix.lower()
    if suffix == ".ris":
        yield from _import_ris(path, source_hint)
    elif suffix in {".csv", ".tsv", ".txt"}:
        delim = "," if suffix == ".csv" else "\t"
        yield from _import_csv(path, source_hint, delim)
    else:
        raise ValueError(f"Unsupported import format: {path}")


# ---------- RIS ----------

# RIS tag mapping. RIS lines look like "TY  - JOUR".
_RIS_TAG_RE = re.compile(r"^([A-Z][A-Z0-9])  - (.*)$")


def _import_ris(path: Path, source_hint: str) -> Iterator[NormalizedRecord]:
    record: dict[str, list[str]] = {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line == "ER  -" or line.startswith("ER  -"):
                if record:
                    yield _ris_to_record(record, source_hint)
                record = {}
                continue
            m = _RIS_TAG_RE.match(line)
            if m:
                tag, val = m.group(1), m.group(2).strip()
                record.setdefault(tag, []).append(val)
            else:
                # continuation of last tag
                if record:
                    last = list(record.keys())[-1]
                    record[last][-1] += " " + line.strip()
    if record:
        yield _ris_to_record(record, source_hint)


def _ris_to_record(rec: dict[str, list[str]], source_hint: str) -> NormalizedRecord:
    title = (rec.get("TI") or rec.get("T1") or rec.get("T2") or [""])[0]
    abstract = (rec.get("AB") or rec.get("N2") or [None])[0]
    doi = (rec.get("DO") or [None])[0]
    year_s = (rec.get("PY") or rec.get("Y1") or [None])[0]
    year = int(year_s[:4]) if year_s and year_s[:4].isdigit() else None
    venue = (rec.get("JO") or rec.get("JF") or rec.get("T2") or [None])[0]
    lang = (rec.get("LA") or [None])[0]
    url = (rec.get("UR") or rec.get("L1") or [None])[0]

    authors = []
    for a in (rec.get("AU") or rec.get("A1") or []):
        if "," in a:
            family, given = [s.strip() for s in a.split(",", 1)]
        else:
            family, given = a, ""
        authors.append({"family": family, "given": given})

    keywords = rec.get("KW") or None
    doctype = (rec.get("TY") or [None])[0]

    # Build a stable source_id. Prefer DOI, else first 80 chars of title.
    sid = doi or f"ris:{title[:80]}"

    return NormalizedRecord(
        source=source_hint,
        source_id=sid,
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        doi=doi,
        venue=venue,
        document_type=doctype,
        language=lang,
        keywords=keywords,
        url=url,
        raw=rec,
    )


# ---------- CSV (Scopus) ----------

# Scopus CSV column names. WoS varies; users can adjust mapping at need.
_CSV_FIELD_MAP = {
    "title":       ["Title", "TI", "Article Title"],
    "abstract":    ["Abstract", "AB"],
    "authors":     ["Authors", "AU", "Author Full Names"],
    "year":        ["Year", "PY", "Publication Year"],
    "doi":         ["DOI", "DI"],
    "venue":       ["Source title", "Source Title", "SO", "Journal"],
    "language":    ["Language of Original Document", "LA", "Language"],
    "doctype":     ["Document Type", "DT"],
    "keywords":    ["Author Keywords", "DE", "Index Keywords", "ID"],
    "url":         ["Link", "DOI Link", "URL"],
}


def _pick(row: dict, names: list[str]) -> str | None:
    for n in names:
        if n in row and row[n]:
            return row[n]
    return None


def _import_csv(path: Path, source_hint: str, delim: str) -> Iterator[NormalizedRecord]:
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delim)
        for row in reader:
            title = _pick(row, _CSV_FIELD_MAP["title"]) or ""
            doi = _pick(row, _CSV_FIELD_MAP["doi"])
            year_s = _pick(row, _CSV_FIELD_MAP["year"])
            year = int(year_s[:4]) if year_s and year_s[:4].isdigit() else None

            authors_raw = _pick(row, _CSV_FIELD_MAP["authors"]) or ""
            authors = []
            for a in re.split(r";\s*|,\s+(?=[A-Z])", authors_raw):
                a = a.strip()
                if not a:
                    continue
                if "," in a:
                    family, given = [s.strip() for s in a.split(",", 1)]
                else:
                    parts = a.rsplit(" ", 1)
                    if len(parts) == 2:
                        given, family = parts
                    else:
                        family, given = a, ""
                authors.append({"family": family, "given": given})

            kw_raw = _pick(row, _CSV_FIELD_MAP["keywords"])
            keywords = [k.strip() for k in re.split(r";\s*", kw_raw)] if kw_raw else None

            sid = doi or f"csv:{title[:80]}"

            yield NormalizedRecord(
                source=source_hint,
                source_id=sid,
                title=title,
                abstract=_pick(row, _CSV_FIELD_MAP["abstract"]),
                authors=authors,
                year=year,
                doi=doi,
                venue=_pick(row, _CSV_FIELD_MAP["venue"]),
                document_type=_pick(row, _CSV_FIELD_MAP["doctype"]),
                language=_pick(row, _CSV_FIELD_MAP["language"]),
                keywords=keywords,
                url=_pick(row, _CSV_FIELD_MAP["url"]),
                raw=dict(row),
            )

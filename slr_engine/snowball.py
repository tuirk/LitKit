"""Snowball sampling.

Backward snowballing: for each included paper, fetch the works it references
and add them as new candidates.
Forward snowballing: for each included paper, fetch the works that cite it
and add them as new candidates.

Methodology follows Wohlin (2014) and TARCiS reporting standards. We use
OpenAlex as the citation source because it's open, comprehensive across
fields, and has both `referenced_works` (backward) and `cited_by_api_url`
(forward) fields.

Default policy:
  - One iteration only. Multi-iteration snowballing has rapidly diminishing
    returns and explodes review size; second-iteration snowballing should be
    a deliberate decision, not a default.
  - Both directions enabled. Backward catches foundational/older work the
    query missed; forward catches newer work and updates.
  - New finds enter the pipeline at the SAME stage as fresh database hits:
    they need title/abstract screening before they're "in".
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Iterator, Optional

from .sources import NormalizedRecord
from .sources.openalex import OpenAlexAdapter, _reconstruct_abstract


def snowball_seed(
    *,
    record_id_value: Optional[str],
    doi: Optional[str],
    direction: str,                       # "backward" or "forward"
    contact_email: Optional[str] = None,
    user_agent: str = "slr-engine/1.0 (research; OA only)",
) -> Iterator[NormalizedRecord]:
    """Walk one paper's references (backward) or citations (forward) via OpenAlex."""
    if direction not in {"backward", "forward"}:
        raise ValueError(f"direction must be 'backward' or 'forward', got {direction!r}")

    # Resolve the seed to an OpenAlex work
    seed_work = _resolve_seed(
        openalex_id=record_id_value, doi=doi,
        contact_email=contact_email, user_agent=user_agent
    )
    if seed_work is None:
        return

    if direction == "backward":
        yield from _walk_backward(seed_work, contact_email, user_agent)
    else:
        yield from _walk_forward(seed_work, contact_email, user_agent)


def _resolve_seed(*, openalex_id, doi, contact_email, user_agent) -> Optional[dict]:
    if openalex_id:
        wid = openalex_id.rsplit("/", 1)[-1]
        url = f"https://api.openalex.org/works/{wid}"
    elif doi:
        url = f"https://api.openalex.org/works/doi:{doi}"
    else:
        return None
    if contact_email:
        url += ("&" if "?" in url else "?") + f"mailto={contact_email}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _walk_backward(seed: dict, contact_email, user_agent) -> Iterator[NormalizedRecord]:
    """Backward = papers the seed references. OpenAlex gives us a list of
    work IDs in `referenced_works`. We fetch their metadata in batches via
    the `filter=ids.openalex:` syntax (up to ~100 per request)."""
    ref_ids = seed.get("referenced_works") or []
    if not ref_ids:
        return
    yield from _batch_fetch_works(ref_ids, contact_email, user_agent)


def _walk_forward(seed: dict, contact_email, user_agent) -> Iterator[NormalizedRecord]:
    """Forward = papers that cite the seed. OpenAlex provides `cited_by_api_url`
    which is a search URL ready to paginate."""
    base = seed.get("cited_by_api_url")
    if not base:
        return

    cursor = "*"
    while True:
        sep = "&" if "?" in base else "?"
        url = f"{base}{sep}per-page=200&cursor={cursor}"
        if contact_email:
            url += f"&mailto={contact_email}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception:
            return

        results = data.get("results") or []
        if not results:
            return
        for w in results:
            yield _work_to_record(w)

        nxt = (data.get("meta") or {}).get("next_cursor")
        if not nxt:
            return
        cursor = nxt
        time.sleep(0.1)


def _batch_fetch_works(work_ids: list[str], contact_email, user_agent) -> Iterator[NormalizedRecord]:
    """Fetch a batch of works by OpenAlex ID list. Filter syntax:
    filter=ids.openalex:W123|W456|W789"""
    BATCH = 50  # well under OpenAlex's 100-id filter limit
    short_ids = [w.rsplit("/", 1)[-1] for w in work_ids]
    for i in range(0, len(short_ids), BATCH):
        batch = short_ids[i : i + BATCH]
        params = {
            "filter": f"openalex:{'|'.join(batch)}",
            "per-page": "200",
        }
        if contact_email:
            params["mailto"] = contact_email
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception:
            continue
        for w in data.get("results") or []:
            yield _work_to_record(w)
        time.sleep(0.1)


def _work_to_record(w: dict) -> NormalizedRecord:
    """Convert an OpenAlex work dict to NormalizedRecord. Same logic as
    the OpenAlex adapter; duplicated here to keep snowball self-contained."""
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

    return NormalizedRecord(
        source="openalex",            # snowball results enter as openalex hits
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
        keywords=[c.get("display_name") for c in (w.get("concepts") or [])
                  if c.get("display_name")],
        url=w.get("doi") or loc.get("landing_page_url"),
        raw=w,
    )

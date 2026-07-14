"""Open-access full-text resolver.

For each record, collect ranked OA URL candidates from lawful sources.
Refuses anything that isn't lawfully obtainable.

Candidate sources (order / ranking priority):
  1. PMC (via PMCID)
  2. Europe PMC (XML + PDF when OA)
  3. OpenAlex OA locations (best + all oa_locations)
  4. Unpaywall OA locations (published → accepted/AAM → submitted)
  5. arXiv PDF (from arXiv id or record URL)
  6. CORE (requires API key)
  7. Crossref text-mining links

`resolve()` returns the best candidate or None.
`resolve_candidates()` returns the full ranked, deduped list.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

USER_AGENT = "slr-engine/1.0 (research; OA only)"

# OA tiers we will attempt to download. Closed/hybrid are skipped at resolve
# and download time.
ALLOWED_OA_TIERS = frozenset({"gold", "green", "bronze"})

_ARXIV_ID_RE = re.compile(
    r"(?:arxiv[.:]?\s*)?(?:abs/|pdf/)?(\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
_ARXIV_OLD_RE = re.compile(
    r"(?:arxiv[.:]?\s*)?(?:abs/|pdf/)?([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?",
    re.IGNORECASE,
)

_VERSION_RANK = {
    "publishedversion": 0,
    "acceptedversion": 1,
    "submittedversion": 2,
}

_SOURCE_RANK = {
    "pmc": 0,
    "europepmc": 1,
    "openalex": 2,
    "unpaywall": 3,
    "arxiv": 4,
    "core": 5,
    "crossref": 6,
}

_FORMAT_RANK = {"pdf": 0, "xml": 1, "html": 2}


def resolve(
    *,
    doi: Optional[str] = None,
    pmid: Optional[str] = None,
    pmcid: Optional[str] = None,
    openalex_id: Optional[str] = None,
    contact_email: Optional[str] = None,
    core_api_key: Optional[str] = None,
    openalex_api_key: Optional[str] = None,
    record_url: Optional[str] = None,
    source: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Optional[dict]:
    """Return the best OA candidate, or None."""
    cands = resolve_candidates(
        doi=doi,
        pmid=pmid,
        pmcid=pmcid,
        openalex_id=openalex_id,
        contact_email=contact_email,
        core_api_key=core_api_key,
        openalex_api_key=openalex_api_key,
        record_url=record_url,
        source=source,
        source_id=source_id,
    )
    return cands[0] if cands else None


def resolve_candidates(
    *,
    doi: Optional[str] = None,
    pmid: Optional[str] = None,
    pmcid: Optional[str] = None,
    openalex_id: Optional[str] = None,
    contact_email: Optional[str] = None,
    core_api_key: Optional[str] = None,
    openalex_api_key: Optional[str] = None,
    record_url: Optional[str] = None,
    source: Optional[str] = None,
    source_id: Optional[str] = None,
) -> list[dict]:
    """Collect ranked, URL-deduped OA download candidates."""
    raw: list[dict] = []

    # 1. PMC
    if pmcid:
        pmc = pmcid if str(pmcid).upper().startswith("PMC") else f"PMC{pmcid}"
        raw.append({
            "resolver_source": "pmc",
            "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/pdf/",
            "license": "pmc-oa",
            "file_format": "pdf",
            "oa_status": "gold",
            "version_rank": 0,
        })

    # 2. Europe PMC
    if pmid or pmcid or doi:
        raw.extend(_collect_europe_pmc(pmid=pmid, pmcid=pmcid, doi=doi))

    # 3. OpenAlex
    if openalex_id or doi:
        raw.extend(_collect_openalex(
            openalex_id=openalex_id,
            doi=doi,
            contact_email=contact_email,
            api_key=openalex_api_key,
        ))

    # 4. Unpaywall
    if doi and contact_email:
        raw.extend(_collect_unpaywall(doi=doi, email=contact_email))

    # 5. arXiv
    raw.extend(_collect_arxiv(
        source=source, source_id=source_id, record_url=record_url, doi=doi,
    ))

    # 6. CORE
    if (doi or pmid) and core_api_key:
        core = _try_core(doi=doi, pmid=pmid, api_key=core_api_key)
        if core:
            core["version_rank"] = 0
            raw.append(core)

    # 7. Crossref text-mining
    if doi:
        raw.extend(_collect_crossref_links(doi=doi))

    return _rank_and_dedupe(raw)


def extract_arxiv_id(
    *,
    source: Optional[str] = None,
    source_id: Optional[str] = None,
    record_url: Optional[str] = None,
    doi: Optional[str] = None,
) -> Optional[str]:
    """Best-effort arXiv id from source fields / URL / DOI."""
    if source and str(source).lower() == "arxiv" and source_id:
        cleaned = _normalize_arxiv_id(str(source_id))
        if cleaned:
            return cleaned

    for blob in (source_id, record_url, doi):
        if not blob:
            continue
        cleaned = _normalize_arxiv_id(str(blob))
        if cleaned:
            return cleaned
    return None


def arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def _normalize_arxiv_id(text: str) -> Optional[str]:
    text = text.strip()
    if "doi.org/10.48550/arxiv." in text.lower():
        text = text.lower().split("arxiv.", 1)[-1]
    m = _ARXIV_ID_RE.search(text)
    if m:
        return m.group(1)
    m = _ARXIV_OLD_RE.search(text)
    if m:
        return m.group(1)
    return None


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    # Strip fragments and trailing slashes for dedupe
    u = u.split("#", 1)[0].rstrip("/")
    return u.lower()


def _file_format_from_url(url: str, default: str = "html") -> str:
    low = url.lower().split("?", 1)[0]
    if low.endswith(".pdf") or "/pdf" in low or low.endswith("/pdf/"):
        return "pdf"
    if low.endswith(".xml") or "fulltextxml" in low:
        return "xml"
    return default


def _rank_and_dedupe(candidates: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in candidates:
        url = (c.get("url") or "").strip()
        if not url:
            continue
        key = _normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        item = dict(c)
        item["url"] = url
        if not item.get("file_format"):
            item["file_format"] = _file_format_from_url(url)
        item.setdefault("version_rank", 9)
        out.append(item)

    out.sort(key=lambda c: (
        _SOURCE_RANK.get(c.get("resolver_source", ""), 99),
        int(c.get("version_rank", 9)),
        _FORMAT_RANK.get(c.get("file_format", "html"), 9),
    ))
    # Drop ranking helper from public dicts (keep optional fields clean)
    for c in out:
        c.pop("version_rank", None)
    return out


def _get_json(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = 30,
) -> Optional[dict]:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _collect_europe_pmc(*, pmid: Optional[str], pmcid: Optional[str],
                        doi: Optional[str]) -> list[dict]:
    if pmcid:
        q = f"PMCID:{pmcid}"
    elif pmid:
        q = f"EXT_ID:{pmid} AND SRC:MED"
    elif doi:
        q = f'DOI:"{doi}"'
    else:
        return []

    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
           + urllib.parse.urlencode({
               "query": q, "format": "json", "resultType": "core",
           }))
    data = _get_json(url)
    if not data:
        return []
    results = data.get("resultList", {}).get("result", [])
    if not results:
        return []
    r = results[0]
    if r.get("isOpenAccess") != "Y":
        return []

    out: list[dict] = []
    license_ = r.get("license") or "epmc-oa"
    epmc_id = r.get("id")
    src = r.get("source", "MED")
    r_pmcid = r.get("pmcid") or pmcid

    if r.get("fullTextIdList") and epmc_id:
        out.append({
            "resolver_source": "europepmc",
            "url": (
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/"
                f"{src}/{epmc_id}/fullTextXML"
            ),
            "license": license_,
            "file_format": "xml",
            "oa_status": "gold",
            "version_rank": 0,
        })

    if r_pmcid:
        pmc = r_pmcid if str(r_pmcid).upper().startswith("PMC") else f"PMC{r_pmcid}"
        out.append({
            "resolver_source": "europepmc",
            "url": f"https://europepmc.org/articles/{pmc}?pdf=render",
            "license": license_,
            "file_format": "pdf",
            "oa_status": "gold",
            "version_rank": 0,
        })
    return out


def _collect_openalex(
    *,
    openalex_id: Optional[str],
    doi: Optional[str],
    contact_email: Optional[str],
    api_key: Optional[str] = None,
) -> list[dict]:
    if openalex_id:
        wid = openalex_id.rsplit("/", 1)[-1]
        url = f"https://api.openalex.org/works/{wid}"
    elif doi:
        url = f"https://api.openalex.org/works/doi:{doi}"
    else:
        return []
    if contact_email:
        url += ("&" if "?" in url else "?") + f"mailto={contact_email}"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = _get_json(url, headers=headers or None)
    if not data:
        return []

    oa_status = (data.get("open_access") or {}).get("oa_status") or "unknown"
    if oa_status not in ALLOWED_OA_TIERS:
        return []

    locations = []
    best = data.get("best_oa_location")
    if best:
        locations.append(best)
    for loc in data.get("oa_locations") or []:
        locations.append(loc)

    out: list[dict] = []
    for loc in locations:
        if not loc or not loc.get("is_oa"):
            continue
        pdf = loc.get("pdf_url") or loc.get("url")
        if not pdf:
            continue
        out.append({
            "resolver_source": "openalex",
            "url": pdf,
            "license": loc.get("license"),
            "file_format": _file_format_from_url(pdf),
            "oa_status": oa_status,
            "version_rank": _VERSION_RANK.get(
                str(loc.get("version") or "").lower().replace("_", ""), 9
            ),
        })
    return out


def _collect_unpaywall(*, doi: str, email: str) -> list[dict]:
    url = (
        f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}"
        f"?email={urllib.parse.quote(email)}"
    )
    data = _get_json(url)
    if not data:
        return []

    oa_status = data.get("oa_status") or "unknown"
    if oa_status not in ALLOWED_OA_TIERS:
        return []

    locations = []
    best = data.get("best_oa_location")
    if best:
        locations.append(best)
    for loc in data.get("oa_locations") or []:
        locations.append(loc)

    out: list[dict] = []
    for loc in locations:
        if not loc:
            continue
        pdf = loc.get("url_for_pdf") or loc.get("url")
        if not pdf:
            continue
        out.append({
            "resolver_source": "unpaywall",
            "url": pdf,
            "license": loc.get("license"),
            "file_format": _file_format_from_url(pdf),
            "oa_status": oa_status,
            "version_rank": _VERSION_RANK.get(
                str(loc.get("version") or "").lower().replace("_", ""), 9
            ),
        })
    return out


def _collect_arxiv(
    *,
    source: Optional[str],
    source_id: Optional[str],
    record_url: Optional[str],
    doi: Optional[str],
) -> list[dict]:
    arxiv_id = extract_arxiv_id(
        source=source, source_id=source_id, record_url=record_url, doi=doi,
    )
    if not arxiv_id:
        return []
    return [{
        "resolver_source": "arxiv",
        "url": arxiv_pdf_url(arxiv_id),
        "license": "arxiv",
        "file_format": "pdf",
        "oa_status": "green",
        "version_rank": 1,
    }]


def _try_core(*, doi: Optional[str], pmid: Optional[str],
              api_key: str) -> Optional[dict]:
    q = f'doi:"{doi}"' if doi else f'pmid:"{pmid}"'
    url = "https://api.core.ac.uk/v3/search/works"
    body = json.dumps({"q": q, "limit": 1}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    pdf = r.get("downloadUrl")
    if not pdf:
        return None
    return {
        "resolver_source": "core",
        "url": pdf,
        "license": (r.get("license") or {}).get("name"),
        "file_format": "pdf",
        "oa_status": "gold",
    }


def _collect_crossref_links(*, doi: str) -> list[dict]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    data = _get_json(url)
    if not data:
        return []
    msg = data.get("message", {})
    out: list[dict] = []
    for link in msg.get("link", []) or []:
        if link.get("intended-application") != "text-mining":
            continue
        link_url = link.get("URL")
        if not link_url:
            continue
        ct = link.get("content-type", "")
        if "pdf" in ct:
            fmt = "pdf"
        elif "xml" in ct:
            fmt = "xml"
        else:
            fmt = _file_format_from_url(link_url)
        out.append({
            "resolver_source": "crossref",
            "url": link_url,
            "license": None,
            "file_format": fmt,
            "oa_status": "gold",
            "version_rank": 0,
        })
    return out

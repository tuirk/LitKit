"""Open-access full-text resolver.

For each record, walk a chain of resolvers and return the best OA URL plus
license info. Refuses anything that isn't lawfully obtainable.

Resolver order:
  1. PMC (via PMCID)
  2. Europe PMC full-text
  3. OpenAlex best_oa_location
  4. Unpaywall (requires email)
  5. CORE (requires API key)
  6. Crossref text-mining links

Returns {resolver_source, url, license, file_format, oa_status} or None.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

USER_AGENT = "litkit/1.0 (research; OA only)"

# OA tiers we will attempt to download. Closed/hybrid are skipped at resolve
# and download time.
ALLOWED_OA_TIERS = frozenset({"gold", "green", "bronze"})


def resolve(
    *,
    doi: Optional[str],
    pmid: Optional[str],
    pmcid: Optional[str],
    openalex_id: Optional[str],
    contact_email: Optional[str] = None,
    core_api_key: Optional[str] = None,
    openalex_api_key: Optional[str] = None,
) -> Optional[dict]:
    """Try resolvers in order. Return first hit or None."""
    # 1. PMC
    if pmcid:
        return {
            "resolver_source": "pmc",
            "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
            "license": "pmc-oa",
            "file_format": "pdf",
            "oa_status": "gold",
        }

    # 2. Europe PMC
    if pmid or pmcid or doi:
        epmc = _try_europe_pmc(pmid=pmid, pmcid=pmcid, doi=doi)
        if epmc:
            return epmc

    # 3. OpenAlex
    if openalex_id or doi:
        oa = _try_openalex(
            openalex_id=openalex_id,
            doi=doi,
            contact_email=contact_email,
            api_key=openalex_api_key,
        )
        if oa:
            return oa

    # 4. Unpaywall (requires email)
    if doi and contact_email:
        up = _try_unpaywall(doi=doi, email=contact_email)
        if up:
            return up

    # 5. CORE
    if (doi or pmid) and core_api_key:
        core = _try_core(doi=doi, pmid=pmid, api_key=core_api_key)
        if core:
            return core

    # 6. Crossref text-mining links (limited but lawful)
    if doi:
        cr = _try_crossref_links(doi=doi)
        if cr:
            return cr

    return None


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


def _try_europe_pmc(*, pmid: Optional[str], pmcid: Optional[str],
                    doi: Optional[str]) -> Optional[dict]:
    if pmcid:
        q = f"PMCID:{pmcid}"
    elif pmid:
        q = f"EXT_ID:{pmid} AND SRC:MED"
    elif doi:
        q = f'DOI:"{doi}"'
    else:
        return None

    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
           + urllib.parse.urlencode({"query": q, "format": "json", "resultType": "core"}))
    data = _get_json(url)
    if not data:
        return None
    results = data.get("resultList", {}).get("result", [])
    if not results:
        return None
    r = results[0]
    if r.get("isOpenAccess") != "Y":
        return None

    epmc_id = r.get("id")
    src = r.get("source", "MED")
    if r.get("fullTextIdList"):
        return {
            "resolver_source": "europepmc",
            "url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{src}/{epmc_id}/fullTextXML",
            "license": r.get("license") or "epmc-oa",
            "file_format": "xml",
            "oa_status": "gold",
        }
    return None


def _try_openalex(
    *,
    openalex_id: Optional[str],
    doi: Optional[str],
    contact_email: Optional[str],
    api_key: Optional[str] = None,
) -> Optional[dict]:
    if openalex_id:
        wid = openalex_id.rsplit("/", 1)[-1]
        url = f"https://api.openalex.org/works/{wid}"
    elif doi:
        url = f"https://api.openalex.org/works/doi:{doi}"
    else:
        return None
    if contact_email:
        url += ("&" if "?" in url else "?") + f"mailto={contact_email}"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = _get_json(url, headers=headers or None)
    if not data:
        return None

    oa_status = (data.get("open_access") or {}).get("oa_status") or "unknown"
    if oa_status not in ALLOWED_OA_TIERS:
        return None

    best = data.get("best_oa_location") or {}
    pdf = best.get("pdf_url") or best.get("url")
    if not pdf or not best.get("is_oa"):
        return None
    return {
        "resolver_source": "openalex",
        "url": pdf,
        "license": best.get("license"),
        "file_format": "pdf" if pdf.lower().endswith(".pdf") else "html",
        "oa_status": oa_status,
    }


def _try_unpaywall(*, doi: str, email: str) -> Optional[dict]:
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
    data = _get_json(url)
    if not data:
        return None

    oa_status = data.get("oa_status") or "unknown"
    if oa_status not in ALLOWED_OA_TIERS:
        return None

    best = data.get("best_oa_location") or {}
    pdf = best.get("url_for_pdf") or best.get("url")
    if not pdf:
        return None
    return {
        "resolver_source": "unpaywall",
        "url": pdf,
        "license": best.get("license"),
        "file_format": "pdf" if pdf.lower().endswith(".pdf") else "html",
        "oa_status": oa_status,
    }


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


def _try_crossref_links(*, doi: str) -> Optional[dict]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    data = _get_json(url)
    if not data:
        return None
    msg = data.get("message", {})
    for link in msg.get("link", []) or []:
        if link.get("intended-application") == "text-mining":
            ct = link.get("content-type", "")
            fmt = "pdf" if "pdf" in ct else "xml" if "xml" in ct else "html"
            return {
                "resolver_source": "crossref",
                "url": link.get("URL"),
                "license": None,
                "file_format": fmt,
                "oa_status": "gold",
            }
    return None

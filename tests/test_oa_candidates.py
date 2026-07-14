"""Unit tests for OA candidate collection and not-downloaded reporting."""
from pathlib import Path

from slr_engine.oa_resolver import (
    extract_arxiv_id,
    resolve_candidates,
    _rank_and_dedupe,
    _collect_openalex,
)
from slr_engine.not_downloaded import suggested_action, write_not_downloaded_report


def test_extract_arxiv_id_from_url_and_doi():
    assert extract_arxiv_id(record_url="https://arxiv.org/abs/2401.12345") == "2401.12345"
    assert extract_arxiv_id(record_url="https://arxiv.org/pdf/2401.12345.pdf") == "2401.12345"
    assert extract_arxiv_id(doi="10.48550/arXiv.2401.12345") == "2401.12345"
    assert extract_arxiv_id(source="arxiv", source_id="2401.12345v2") == "2401.12345"


def test_rank_and_dedupe_prefers_pdf_and_dedupes_urls():
    ranked = _rank_and_dedupe([
        {
            "resolver_source": "openalex",
            "url": "https://example.org/paper",
            "file_format": "html",
            "oa_status": "gold",
            "version_rank": 0,
        },
        {
            "resolver_source": "openalex",
            "url": "https://example.org/paper/",  # same after normalize
            "file_format": "html",
            "oa_status": "gold",
            "version_rank": 0,
        },
        {
            "resolver_source": "pmc",
            "url": "https://ncbi.nlm.nih.gov/pmc/articles/PMC1/pdf/",
            "file_format": "pdf",
            "oa_status": "gold",
            "version_rank": 0,
        },
        {
            "resolver_source": "unpaywall",
            "url": "https://repo.example/aam.pdf",
            "file_format": "pdf",
            "oa_status": "green",
            "version_rank": 1,
        },
    ])
    assert len(ranked) == 3
    assert ranked[0]["resolver_source"] == "pmc"
    assert ranked[0]["file_format"] == "pdf"


def test_openalex_multi_location(monkeypatch):
    payload = {
        "open_access": {"oa_status": "green"},
        "best_oa_location": {
            "is_oa": True,
            "pdf_url": "https://ex.org/best.pdf",
            "license": "cc-by",
            "version": "publishedVersion",
        },
        "oa_locations": [
            {
                "is_oa": True,
                "pdf_url": "https://ex.org/aam.pdf",
                "license": "cc-by",
                "version": "acceptedVersion",
            },
            {
                "is_oa": False,
                "pdf_url": "https://ex.org/closed.pdf",
            },
        ],
    }
    monkeypatch.setattr(
        "slr_engine.oa_resolver._get_json", lambda *a, **k: payload
    )
    locs = _collect_openalex(
        openalex_id="W123", doi=None, contact_email=None, api_key=None,
    )
    urls = {c["url"] for c in locs}
    assert "https://ex.org/best.pdf" in urls
    assert "https://ex.org/aam.pdf" in urls
    assert "https://ex.org/closed.pdf" not in urls


def test_unpaywall_version_ranking(monkeypatch):
    payload = {
        "oa_status": "green",
        "best_oa_location": {
            "url_for_pdf": "https://ex.org/submitted.pdf",
            "version": "submittedVersion",
        },
        "oa_locations": [
            {
                "url_for_pdf": "https://ex.org/accepted.pdf",
                "version": "acceptedVersion",
            },
            {
                "url_for_pdf": "https://ex.org/published.pdf",
                "version": "publishedVersion",
            },
        ],
    }
    monkeypatch.setattr(
        "slr_engine.oa_resolver._get_json", lambda *a, **k: payload
    )
    cands = resolve_candidates(doi="10.1/x", contact_email="a@b.com")
    # After rank: pmc/epmc none; unpaywall published before accepted/submitted
    unpaywall = [c for c in cands if c["resolver_source"] == "unpaywall"]
    assert unpaywall[0]["url"] == "https://ex.org/published.pdf"


def test_suggested_action():
    assert suggested_action(doi="10.1/x", url=None) == "ILL"
    assert suggested_action(
        doi=None, url="https://arxiv.org/abs/2401.12345",
    ) == "check_preprint"
    assert suggested_action(doi=None, url="https://example.org/p") == "author_request"
    assert suggested_action(doi=None, url=None) == "none_found"


def test_write_not_downloaded_report(tmp_path: Path):
    rows = [{
        "canonical_id": "rec1",
        "title": "A study",
        "year": 2020,
        "doi": "10.1/x",
        "pmid": None,
        "pmcid": None,
        "url": None,
        "download_status": "failed",
        "resolver_source": "openalex",
        "error": "404",
        "suggested_action": "ILL",
    }]
    csv_path, txt_path = write_not_downloaded_report(tmp_path, rows)
    assert csv_path.exists()
    assert txt_path.exists()
    text = txt_path.read_text(encoding="utf-8")
    assert "rec1" in text
    assert "Suggested: ILL" in text
    assert "10.1/x" in csv_path.read_text(encoding="utf-8")

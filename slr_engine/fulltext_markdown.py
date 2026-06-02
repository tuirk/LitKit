"""Normalize downloaded full text into Markdown with MarkItDown.

The review pipeline may download HTML, XML, or PDF files, and some providers
serve PDF bytes behind misleading .html URLs. This helper sniffs the content,
runs it through Microsoft MarkItDown, persists a .md sidecar, and returns a
truncated excerpt suitable for screening / extraction batches.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

def _get_markitdown():
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise ImportError("markitdown is required. pip install markitdown") from e
    return MarkItDown()


_MARKITDOWN = None


def _markitdown():
    global _MARKITDOWN
    if _MARKITDOWN is None:
        _MARKITDOWN = _get_markitdown()
    return _MARKITDOWN


@dataclass
class MarkdownConversionResult:
    markdown_path: Optional[Path]
    excerpt: Optional[str]
    intro_conclusion_excerpt: Optional[str]
    detected_format: str
    error: Optional[str] = None


def convert_to_markdown(
    source_path: Path,
    markdown_dir: Path,
    max_chars: int = 30000,
) -> MarkdownConversionResult:
    """Convert any downloaded full-text file to Markdown.

    A .md sidecar is written under ``markdown_dir`` using the canonical stem
    from the downloaded file name. Returns the sidecar path plus a truncated
    excerpt for JSONL batches.
    """
    markdown_dir.mkdir(parents=True, exist_ok=True)
    detected_format = _detect_format(source_path)
    markdown_path = markdown_dir / f"{source_path.stem}.md"

    try:
        markdown = _convert_with_markitdown(source_path, detected_format)
    except Exception as exc:
        return MarkdownConversionResult(
            markdown_path=None,
            excerpt=None,
            intro_conclusion_excerpt=None,
            detected_format=detected_format,
            error=f"{type(exc).__name__}: {exc}",
        )

    markdown = _clean_markdown(markdown)
    markdown_path.write_text(markdown, encoding="utf-8")
    return MarkdownConversionResult(
        markdown_path=markdown_path,
        excerpt=_truncate(markdown, max_chars=max_chars),
        intro_conclusion_excerpt=_extract_intro_conclusion_excerpt(markdown),
        detected_format=detected_format,
        error=None,
    )


def _convert_with_markitdown(source_path: Path, detected_format: str) -> str:
    # MarkItDown relies on file type hints. Some publishers return PDF bytes
    # behind a .html path, so write a temporary file with the detected suffix.
    if detected_format != source_path.suffix.lower().lstrip("."):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / f"{source_path.stem}.{detected_format}"
            temp_path.write_bytes(source_path.read_bytes())
            result = _markitdown().convert(temp_path)
    else:
        result = _markitdown().convert(source_path)

    markdown = getattr(result, "markdown", None) or getattr(
        result, "text_content", None
    )
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError(f"MarkItDown returned no text for {source_path.name}")
    return markdown


def _detect_format(source_path: Path) -> str:
    head = source_path.read_bytes()[:512].lstrip()
    lower = head.lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if lower.startswith(b"<?xml"):
        return "xml"
    if lower.startswith(b"<!doctype html") or lower.startswith(b"<html"):
        return "html"
    suffix = source_path.suffix.lower().lstrip(".")
    return suffix or "html"


def _clean_markdown(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\ufeff", "")
    return cleaned.strip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head_chars = max(0, max_chars - 5000)
    head = text[:head_chars]
    tail = text[-5000:]
    return f"{head}\n\n[...truncated...]\n\n{tail}"


def _extract_intro_conclusion_excerpt(text: str, max_chars: int = 12000) -> Optional[str]:
    intro = _extract_section_window(
        text,
        patterns=[
            r"(?im)^(?:#+\s*)?introduction\s*$",
            r"(?im)^(?:#+\s*)?background\s*$",
        ],
        window_chars=6000,
    )
    conclusion = _extract_section_window(
        text,
        patterns=[
            r"(?im)^(?:#+\s*)?conclusions?\s*$",
            r"(?im)^(?:#+\s*)?discussion\s+and\s+conclusions?\s*$",
            r"(?im)^(?:#+\s*)?summary\s+and\s+conclusions?\s*$",
            r"(?im)^(?:#+\s*)?discussion\s*$",
            r"(?im)^(?:#+\s*)?final\s+remarks\s*$",
        ],
        window_chars=6000,
    )
    if not intro and not conclusion:
        return None

    parts = []
    if intro:
        parts.append("## Introduction\n\n" + intro.strip())
    if conclusion:
        parts.append("## Conclusion\n\n" + conclusion.strip())
    joined = "\n\n".join(parts).strip()
    return _truncate(joined, max_chars=max_chars)


def _extract_section_window(text: str, patterns: list[str], window_chars: int) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        start = match.end()
        end = _find_next_heading(text, start)
        if end is None:
            end = min(len(text), start + window_chars)
        section = text[start:end].strip()
        if section:
            return section[:window_chars]
    return None


def _find_next_heading(text: str, start: int) -> Optional[int]:
    heading_re = re.compile(
        r"(?im)^(?:#+\s*)?(?:abstract|introduction|background|methods?|materials?\s+and\s+methods?|results?|discussion(?:\s+and\s+conclusions?)?|conclusions?|references)\s*$"
    )
    match = heading_re.search(text, pos=start)
    return match.start() if match else None

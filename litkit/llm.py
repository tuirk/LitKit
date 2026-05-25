"""LLM adapter for screening, extraction, and quality assessment.

Tasks:
  - screen:             include/exclude/unsure for one record (title+abstract)
  - extract:            structured fields from full text
  - screen_and_extract: both in one combined call (full-text pass)

Each task can optionally include quality assessment fields.

Pluggable across providers. API keys come from environment variables.
This module is OPTIONAL — default is the agent screening manually.

Providers:
  - anthropic   (env: ANTHROPIC_API_KEY)
  - deepseek    (env: DEEPSEEK_API_KEY)
  - google      (env: GOOGLE_API_KEY)

Configure in project.yaml:
  llm:
    provider: anthropic
    model: claude-sonnet-4-5
    temperature: 0
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .env import load_dotenv


load_dotenv()


# ---------------------------------------------------------------------
# Generic extraction schema
# ---------------------------------------------------------------------
# Domain-neutral, designed for AI/ML/tech/finance/maths reviews.
# Override per project via project.yaml's `extraction.custom_fields`.

GENERIC_EXTRACTION_FIELDS: list[dict] = [
    {
        "name": "summary",
        "type": "string",
        "description": (
            "2-3 sentence overview followed by 3-5 key findings as bullet "
            "points (each starting with '- '). Findings should be concrete "
            "and self-contained — include numbers, percentages, metrics, "
            "and effect sizes whenever the paper provides them."
        ),
    },
    {
        "name": "context",
        "type": "string",
        "description": (
            "2-3 sentences situating this paper. What kind of work it is "
            "(empirical, theoretical, methods, survey), what broader question "
            "it tackles, what makes it notable. Written for someone who "
            "hasn't read it."
        ),
    },
    {
        "name": "approach",
        "type": "string",
        "description": (
            "Short prose describing what they actually did — the technical "
            "heart of the paper. Method, algorithm, architecture, model "
            "class, or proof technique. Be specific."
        ),
    },
    {
        "name": "data_or_setup",
        "type": "string",
        "description": (
            "What they ran it on. Datasets, markets and time period, "
            "benchmarks, simulation parameters, theoretical setting. "
            "Empty string if pure theory with no setup."
        ),
    },
    {
        "name": "key_results",
        "type": "list",
        "description": (
            "List of concrete findings. Each item: "
            '{"claim": "...", "evidence": "..."}. '
            "claim is what the paper concludes; evidence is the specific "
            "number, metric, or observation backing it. Include as many as "
            "the paper actually supports — could be 1, could be 8."
        ),
    },
    {
        "name": "relevance_notes",
        "type": "string",
        "description": (
            "One sentence on why this paper is relevant to THIS review's "
            "research question specifically. Bridges generic extraction to "
            "the review you're doing."
        ),
    },
]


# Risk-of-bias / critical-appraisal fields. Always the same shape regardless
# of project. Populated only when the caller passes with_quality=True.
# The legacy "quality" name is kept in code for backward compatibility, but
# PRISMA reporting should use the risk_of_bias_* fields below.
QUALITY_FIELDS: list[dict] = [
    {
        "name": "risk_of_bias_tool",
        "type": "string",
        "description": (
            "Tool or rubric used for this judgement. Use a named domain tool "
            "when project criteria specify one; otherwise use "
            "'LitKit domain-based risk-of-bias rubric'."
        ),
    },
    {
        "name": "risk_of_bias_overall",
        "type": "enum",
        "values": ["low", "some_concerns", "high", "unclear"],
        "description": (
            "Overall risk of bias for the study/result most relevant to this "
            "review, not generic paper quality."
        ),
    },
    {
        "name": "risk_of_bias_domains",
        "type": "list",
        "description": (
            "List of domain judgements. Each item should be an object with "
            "domain, judgement (low/some_concerns/high/unclear), rationale, "
            "and short evidence_quote when available. Use domains relevant "
            "to the design, such as selection, confounding, missing data, "
            "outcome measurement, selective reporting, data leakage, "
            "baseline/comparator adequacy, and reproducibility."
        ),
    },
    {
        "name": "risk_of_bias_notes",
        "type": "string",
        "description": (
            "1-2 sentence justification for the overall risk-of-bias "
            "judgement, citing concrete design/conduct/reporting features."
        ),
    },
    {
        "name": "methodological_rigor",
        "type": "enum",
        "values": ["high", "medium", "low", "unclear"],
        "description": (
            "Was the work done carefully? Consider: sample size, presence "
            "of holdout/test sets, statistical tests with proper baselines, "
            "reproducibility info, ablations. 'unclear' if the paper "
            "doesn't say enough."
        ),
    },
    {
        "name": "evidence_strength",
        "type": "enum",
        "values": ["strong", "moderate", "weak", "unclear"],
        "description": (
            "Do the results actually support the claims? Effect sizes vs "
            "noise, robustness checks, sensitivity to choices. 'weak' if "
            "claims clearly outrun evidence."
        ),
    },
    {
        "name": "limitations_acknowledged",
        "type": "enum",
        "values": ["yes", "partial", "no"],
        "description": (
            "Does the paper honestly discuss what it doesn't show? "
            "Threats to validity, scope limits, alternative explanations."
        ),
    },
    {
        "name": "quality_notes",
        "type": "string",
        "description": (
            "1-2 sentences flagging specific concerns OR strengths. "
            "Examples of concerns: data leakage, p-hacking, n=1 demo, no "
            "baselines, cherry-picked benchmark, train/test contamination. "
            "Examples of strengths: pre-registered, large-scale OOS test, "
            "negative results reported. Be specific."
        ),
    },
]


# ---------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------

@dataclass
class ScreeningResult:
    decision: str                 # include / exclude / unsure
    reason: str
    criteria_hit: list[str]
    raw_response: str = ""


@dataclass
class ExtractionResult:
    fields: dict                  # {field_name: value}
    quality: Optional[dict] = None  # populated if with_quality=True
    raw_response: str = ""


@dataclass
class CombinedResult:
    screening: ScreeningResult
    extraction: ExtractionResult


class LLMError(Exception):
    pass


# ---------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------

_SCREEN_SYSTEM = """You are a screening assistant for a systematic literature review.

Given the review question, inclusion/exclusion criteria with IDs, seed examples, and one paper's title and abstract: decide include / exclude / unsure, give a one-sentence reason, list the criterion IDs you applied.

Hard rules:
1. Apply criteria literally. Do not relax them.
2. If the abstract is missing or genuinely ambiguous, output "unsure". Do not guess.
3. Reason is ONE sentence.
4. Be consistent: same paper-type, same decision.
5. Output ONLY a JSON object: no prose, no markdown fences."""


_EXTRACT_SYSTEM_HEADER = """You are a research analyst for a systematic literature review.

You will be given a paper (title, abstract, full-text excerpt) and a list of fields to populate. Read the paper, fill in the fields with content the paper actually contains.

Hard rules:
- Be concrete. Include numbers, metrics, named methods.
- Do not invent findings the paper doesn't state.
- For string fields the paper doesn't address: use "".
- For list fields the paper doesn't support: use [].
- Output ONLY a JSON object: no prose, no markdown fences."""


_COMBINED_SYSTEM_HEADER = """You are a research analyst for a systematic literature review.

In ONE response you do TWO things:
  1. SCREEN — decide include/exclude/unsure with one-sentence reason and criteria IDs
  2. EXTRACT — populate the requested fields from the paper's content

Hard rules for screening:
- Apply criteria literally. Do not relax them.
- If the full text contradicts the abstract, the full text wins.
- Reason is ONE sentence. If longer needed, use "unsure".

Hard rules for extraction:
- Be concrete: numbers, metrics, named methods.
- Do not invent findings.
- "" for missing string fields, [] for missing list fields.
- If you decided exclude/unsure, you MAY still extract — the data is useful
  for the audit log even for excluded papers — but if you can't tell what
  the paper is about, leave fields empty.

Output ONLY a JSON object."""


_QUALITY_INSTRUCTION_BLOCK = """

ADDITIONAL: populate PRISMA-oriented risk-of-bias fields. Do not treat this
as generic paper quality or prestige. Risk of bias is about whether the study
design, conduct, analysis, or reporting could systematically distort the
finding relevant to this review.

Use a named tool if the project specifies one. Otherwise use the engine's
domain-based rubric and give domain-level judgements with concrete evidence
from the paper. Be specific in risk_of_bias_notes and quality_notes; do not
write vague phrases like 'good methodology' or 'quality concerns'."""


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def screen_record(
    *,
    provider: str,
    model: str,
    question: str,
    inclusion: list[dict],
    exclusion: list[dict],
    seed_examples: dict,
    record: dict,
    temperature: float = 0.0,
    timeout: int = 60,
) -> ScreeningResult:
    """Title/abstract screening only."""
    user = _build_screen_user(
        question=question, inclusion=inclusion, exclusion=exclusion,
        seed_examples=seed_examples, record=record,
    )
    text = _dispatch(provider, model, _SCREEN_SYSTEM, user,
                     temperature, timeout, max_tokens=512)
    return _parse_screen(text)


def build_screen_prompt_packet(
    *,
    question: str,
    inclusion: list[dict],
    exclusion: list[dict],
    seed_examples: dict,
    record: dict,
) -> dict:
    """Return the exact prompt packet for title/abstract screening."""
    return {
        "task": "screen",
        "system": _SCREEN_SYSTEM,
        "user": _build_screen_user(
            question=question,
            inclusion=inclusion,
            exclusion=exclusion,
            seed_examples=seed_examples,
            record=record,
        ),
        "response_shape": {
            "decision": 'include|exclude|unsure',
            "reason": "one sentence",
            "criteria_hit": ["I1"]
        }
    }


def extract_record(
    *,
    provider: str,
    model: str,
    question: str,
    record: dict,
    fields: list[dict],
    with_quality: bool = False,
    temperature: float = 0.0,
    timeout: int = 90,
) -> ExtractionResult:
    """Extraction only. For post-hoc runs over already-screened papers."""
    system = _build_extract_system(fields, with_quality=with_quality)
    user = _build_extract_user(question=question, record=record)
    text = _dispatch(provider, model, system, user,
                     temperature, timeout, max_tokens=2048)
    return _parse_extract(text, fields, with_quality=with_quality)


def build_extract_prompt_packet(
    *,
    question: str,
    record: dict,
    fields: list[dict],
    with_quality: bool = False,
) -> dict:
    """Return the exact prompt packet for extraction / quality."""
    return {
        "task": "extract" if not with_quality else "extract_with_quality",
        "system": _build_extract_system(fields, with_quality=with_quality),
        "user": _build_extract_user(question=question, record=record),
        "fields": fields,
        "with_quality": with_quality,
    }


def screen_and_extract(
    *,
    provider: str,
    model: str,
    question: str,
    inclusion: list[dict],
    exclusion: list[dict],
    seed_examples: dict,
    record: dict,
    fields: list[dict],
    with_quality: bool = False,
    temperature: float = 0.0,
    timeout: int = 120,
) -> CombinedResult:
    """One call returning both a screening recommendation and extraction.
    Used during full-text LLM pass — model reads the paper anyway."""
    system = _build_combined_system(fields, with_quality=with_quality)
    user = _build_combined_user(
        question=question, inclusion=inclusion, exclusion=exclusion,
        seed_examples=seed_examples, record=record,
    )
    text = _dispatch(provider, model, system, user,
                     temperature, timeout, max_tokens=2560)
    return _parse_combined(text, fields, with_quality=with_quality)


def build_combined_prompt_packet(
    *,
    question: str,
    inclusion: list[dict],
    exclusion: list[dict],
    seed_examples: dict,
    record: dict,
    fields: list[dict],
    with_quality: bool = False,
) -> dict:
    """Return the exact prompt packet for combined full-text review."""
    return {
        "task": "screen_and_extract"
        if not with_quality else "screen_extract_and_quality",
        "system": _build_combined_system(fields, with_quality=with_quality),
        "user": _build_combined_user(
            question=question,
            inclusion=inclusion,
            exclusion=exclusion,
            seed_examples=seed_examples,
            record=record,
        ),
        "fields": fields,
        "with_quality": with_quality,
        "response_shape": {
            "decision": 'include|exclude|unsure',
            "reason": "one sentence",
            "criteria_hit": ["I1"],
            "extraction": "object with requested fields",
            "quality": "object with requested quality fields when enabled",
        },
    }


def get_extraction_fields(cfg_extraction: Optional[dict]) -> list[dict]:
    """Resolve project.yaml's `extraction:` config to a list of field dicts.

    Shape:
      None or {} or {"preset": "generic"}     → GENERIC_EXTRACTION_FIELDS
      {"preset": "generic", "custom_fields": [...]} → generic + custom
      {"preset": "none", "custom_fields": [...]}    → custom only
    """
    if not cfg_extraction:
        return list(GENERIC_EXTRACTION_FIELDS)
    preset = cfg_extraction.get("preset", "generic")
    custom = cfg_extraction.get("custom_fields") or []

    if preset == "generic":
        base = list(GENERIC_EXTRACTION_FIELDS)
    elif preset == "none":
        base = []
    else:
        raise LLMError(f"Unknown extraction preset: {preset!r}")

    for cf in custom:
        if "name" not in cf or "description" not in cf:
            raise LLMError(f"Custom extraction field missing name/description: {cf}")
        cf.setdefault("type", "string")
        # If a custom field shares a name with a generic field, override
        base = [f for f in base if f["name"] != cf["name"]]
        base.append(cf)
    return base


# ---------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------

def _criteria_block(inclusion, exclusion, seed_examples) -> str:
    inc = "\n".join(f"- {c['id']}: {c['text']}" for c in inclusion) or "(none)"
    exc = "\n".join(f"- {c['id']}: {c['text']}" for c in exclusion) or "(none)"
    inc_seeds = "\n".join(f"- {s}" for s in seed_examples.get("include", [])) or "(none)"
    exc_seeds = "\n".join(f"- {s}" for s in seed_examples.get("exclude", [])) or "(none)"
    return (
        f"## Inclusion criteria\n{inc}\n\n"
        f"## Exclusion criteria\n{exc}\n\n"
        f"## Seed examples (should INCLUDE)\n{inc_seeds}\n\n"
        f"## Seed examples (should EXCLUDE)\n{exc_seeds}"
    )


def _record_block(record: dict, *, include_fulltext: bool) -> str:
    lines = [
        f"Title: {record.get('title') or '(missing)'}",
        f"Year: {record.get('year') or '(missing)'}",
        f"Venue: {record.get('venue') or '(missing)'}",
        f"Abstract: {record.get('abstract') or '(missing)'}",
    ]
    if include_fulltext:
        ic = record.get("intro_conclusion_excerpt")
        if ic:
            lines.append(f"\nIntroduction/conclusion excerpt:\n{ic}")
        ft = record.get("fulltext_excerpt")
        if ft:
            lines.append(f"\nFull-text excerpt:\n{ft}")
        else:
            lines.append("\nFull-text excerpt: (not available)")
    return "\n".join(lines)


def _format_fields_for_prompt(fields: list[dict]) -> str:
    lines = ["Required JSON keys for the extraction object:"]
    for f in fields:
        ftype = f.get("type", "string")
        lines.append(f'  - "{f["name"]}" ({ftype}): {f["description"]}')
    return "\n".join(lines)


def _format_quality_for_prompt() -> str:
    lines = ["Required JSON keys for the quality object:"]
    for f in QUALITY_FIELDS:
        if f["type"] == "enum":
            vals = " | ".join(f"\"{v}\"" for v in f["values"])
            lines.append(f'  - "{f["name"]}" (one of {vals}): {f["description"]}')
        else:
            lines.append(f'  - "{f["name"]}" (string): {f["description"]}')
    return "\n".join(lines)


def _build_screen_user(*, question, inclusion, exclusion, seed_examples, record) -> str:
    return (
        f"## Review question\n{question}\n\n"
        f"{_criteria_block(inclusion, exclusion, seed_examples)}\n\n"
        f"## Paper\n{_record_block(record, include_fulltext=False)}\n\n"
        'Output the JSON now. Shape: '
        '{"decision": "include"|"exclude"|"unsure", "reason": "...", "criteria_hit": ["I1"]}'
    )


def _build_extract_system(fields: list[dict], *, with_quality: bool) -> str:
    body = _EXTRACT_SYSTEM_HEADER + "\n\n" + _format_fields_for_prompt(fields)
    if with_quality:
        body += _QUALITY_INSTRUCTION_BLOCK + "\n\n" + _format_quality_for_prompt()
        body += (
            "\n\nThe response JSON has TWO top-level keys:\n"
            '  "fields": {<extraction fields above>}\n'
            '  "quality": {<quality fields above>}'
        )
    else:
        body += (
            "\n\nThe response JSON has ONE top-level key: "
            '"fields": {<extraction fields above>}'
        )
    return body


def _build_extract_user(*, question, record) -> str:
    return (
        f"## Review question (relevance context)\n{question}\n\n"
        f"## Paper\n{_record_block(record, include_fulltext=True)}\n\n"
        "Output the JSON now."
    )


def _build_combined_system(fields: list[dict], *, with_quality: bool) -> str:
    body = (
        _COMBINED_SYSTEM_HEADER
        + "\n\nThe response JSON has these top-level keys:\n"
        '  "decision": "include"|"exclude"|"unsure"\n'
        '  "reason": one sentence string\n'
        '  "criteria_hit": list of criterion IDs (strings)\n'
        '  "extraction": object with extraction fields (below)'
    )
    if with_quality:
        body += '\n  "quality": object with quality fields (below)'
    body += "\n\n" + _format_fields_for_prompt(fields)
    if with_quality:
        body += _QUALITY_INSTRUCTION_BLOCK + "\n\n" + _format_quality_for_prompt()
    return body


def _build_combined_user(*, question, inclusion, exclusion, seed_examples, record) -> str:
    return (
        f"## Review question\n{question}\n\n"
        f"{_criteria_block(inclusion, exclusion, seed_examples)}\n\n"
        f"## Paper\n{_record_block(record, include_fulltext=True)}\n\n"
        "Output the JSON now."
    )


# ---------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return text


def _parse_json(text: str) -> dict:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Could not parse JSON from model: {e}\nGot: {text[:300]}")


def _parse_screen(text: str) -> ScreeningResult:
    obj = _parse_json(text)
    decision = obj.get("decision")
    if decision not in {"include", "exclude", "unsure"}:
        raise LLMError(f"Invalid decision: {decision!r}")
    return ScreeningResult(
        decision=decision,
        reason=str(obj.get("reason", ""))[:500],
        criteria_hit=list(obj.get("criteria_hit") or []),
        raw_response=text,
    )


def _extract_fields_from_obj(obj: dict, fields: list[dict]) -> dict:
    out = {}
    for f in fields:
        empty = [] if f.get("type") == "list" else ""
        out[f["name"]] = obj.get(f["name"], empty)
    return out


def _quality_from_obj(obj: dict) -> dict:
    out = {}
    for f in QUALITY_FIELDS:
        empty = [] if f.get("type") == "list" else ""
        out[f["name"]] = obj.get(f["name"], empty)
    return out


def _parse_extract(text: str, fields: list[dict], *,
                   with_quality: bool) -> ExtractionResult:
    obj = _parse_json(text)
    fields_obj = obj.get("fields") or obj  # tolerate flat structure
    extraction_fields = _extract_fields_from_obj(fields_obj, fields)
    quality = None
    if with_quality:
        q_obj = obj.get("quality") or {}
        quality = _quality_from_obj(q_obj)
    return ExtractionResult(fields=extraction_fields, quality=quality,
                            raw_response=text)


def _parse_combined(text: str, fields: list[dict], *,
                    with_quality: bool) -> CombinedResult:
    obj = _parse_json(text)
    decision = obj.get("decision")
    if decision not in {"include", "exclude", "unsure"}:
        raise LLMError(f"Invalid decision: {decision!r}")
    screening = ScreeningResult(
        decision=decision,
        reason=str(obj.get("reason", ""))[:500],
        criteria_hit=list(obj.get("criteria_hit") or []),
        raw_response=text,
    )
    ext_obj = obj.get("extraction") or {}
    extraction_fields = _extract_fields_from_obj(ext_obj, fields)
    quality = None
    if with_quality:
        q_obj = obj.get("quality") or {}
        quality = _quality_from_obj(q_obj)
    extraction = ExtractionResult(fields=extraction_fields, quality=quality,
                                  raw_response=text)
    return CombinedResult(screening=screening, extraction=extraction)


# ---------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------

def _dispatch(provider, model, system, user, temperature, timeout, max_tokens) -> str:
    if provider == "anthropic":
        return _call_anthropic(model, system, user, temperature, timeout, max_tokens)
    if provider == "deepseek":
        return _call_deepseek(model, system, user, temperature, timeout, max_tokens)
    if provider == "google":
        return _call_google(model, system, user, temperature, timeout, max_tokens)
    raise LLMError(f"Unknown provider: {provider}")


def _call_anthropic(model, system, user, temperature, timeout, max_tokens) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    for b in data.get("content", []):
        if b.get("type") == "text":
            return b["text"]
    raise LLMError(f"No text block in Anthropic response: {data}")


def _call_deepseek(model, system, user, temperature, timeout, max_tokens) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise LLMError("DEEPSEEK_API_KEY not set")
    body = json.dumps({
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"Empty choices from DeepSeek: {data}")
    return choices[0].get("message", {}).get("content", "")


def _call_google(model, system, user, temperature, timeout, max_tokens) -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise LLMError("GOOGLE_API_KEY not set")
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }).encode()
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError(f"Empty candidates from Google: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise LLMError(f"No parts in Google response: {data}")
    return parts[0].get("text", "")

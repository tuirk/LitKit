"""Vocabulary extraction for query construction.

Two-stage process, both required for good queries:

  1. KeyBERT extracts ~30-50 candidate phrases from seed paper text.
     Statistical anchor — every phrase is grounded in real seed content.
     If keybert isn't installed, falls back to a degraded heuristic mode
     (keyword frequency from seed text); the agent should ask the user
     to install keybert for proper extraction.

  2. LLM curates the KeyBERT bucket: picks the strong concept-defining
     phrases, drops weak/generic ones, adds known synonyms from broader
     literatures (only as expansions of bucketed terms, not invented from
     scratch), groups into concept clusters ready for PICOC mapping.

The agent shows the curated vocabulary to the user before any goes into
queries. The user confirms or edits.

Constraint baked into the LLM prompt: don't invent terms not present in
or directly synonymous with the bucket. Generic associations from general
knowledge are explicitly out of scope.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import os
from dataclasses import dataclass
from typing import Optional

from .env import load_dotenv


load_dotenv()


# ---------------------------------------------------------------------
# KeyBERT extraction
# ---------------------------------------------------------------------

@dataclass
class CandidatePhrase:
    phrase: str
    score: float
    seed_count: int = 0   # how many seeds this phrase appeared in (when known)


def keybert_available() -> bool:
    """Cheap import check. Agent can call this before deciding whether to
    prompt for install."""
    try:
        import keybert  # noqa: F401
        return True
    except ImportError:
        return False


def extract_with_keybert(seed_records: list[dict],
                         top_n: int = 50,
                         keyphrase_ngram_range: tuple[int, int] = (1, 3),
                         ) -> list[CandidatePhrase]:
    """KeyBERT extraction over seed text.

    Concatenates each seed's title + abstract + full_text_excerpt (when
    available), runs KeyBERT to surface candidate phrases.

    If KeyBERT is not installed, falls back to a frequency-based extractor
    (clearly degraded — caller should warn the user).
    """
    seed_texts = []
    for rec in seed_records:
        if rec.get("error"):
            continue
        parts = [
            rec.get("title", ""),
            rec.get("abstract", ""),
            rec.get("full_text_excerpt", "") or "",
        ]
        # OpenAlex concept names are also useful signal
        for c in (rec.get("concepts") or []):
            if isinstance(c, dict):
                parts.append(c.get("name", ""))
        # Author keywords
        parts.extend(rec.get("keywords", []))
        text = " ".join(p for p in parts if p)
        if text.strip():
            seed_texts.append(text)

    if not seed_texts:
        return []

    if keybert_available():
        return _keybert_extract(seed_texts, top_n, keyphrase_ngram_range)
    return _fallback_frequency_extract(seed_texts, top_n,
                                        keyphrase_ngram_range)


def _keybert_extract(seed_texts: list[str], top_n: int,
                     ngram_range: tuple[int, int]) -> list[CandidatePhrase]:
    """The real KeyBERT path. If the sentence-transformer model can't be
    loaded (network blocked, no disk cache, etc.), falls back to the
    frequency-based extractor."""
    try:
        from keybert import KeyBERT  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        # Prefer a strict offline load from the local cache so KeyBERT does not
        # hit Hugging Face metadata endpoints on environments with blocked
        # network access.
        embedder = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2",
            local_files_only=True,
        )
        kb = KeyBERT(model=embedder)
    except Exception as e:
        # Model couldn't load from the local cache (or the cache is missing /
        # broken). Fall back to the frequency extractor rather than trying to
        # resolve the model online and failing noisily in restricted runtimes.
        print(f"  [vocab] KeyBERT model load failed ({type(e).__name__}); "
              "falling back to frequency-based extraction")
        return _fallback_frequency_extract(seed_texts, top_n, ngram_range)

    # Track per-document phrase appearance for seed_count
    phrase_to_count: dict[str, int] = {}
    phrase_to_score: dict[str, float] = {}

    # Run KeyBERT on each seed separately so we can count seed appearances,
    # then aggregate
    for text in seed_texts:
        try:
            keywords = kb.extract_keywords(
                text,
                keyphrase_ngram_range=ngram_range,
                stop_words="english",
                top_n=top_n,
                use_mmr=True, diversity=0.3,
            )
        except Exception:
            continue
        for phrase, score in keywords:
            phrase_low = phrase.lower().strip()
            if not phrase_low:
                continue
            phrase_to_count[phrase_low] = phrase_to_count.get(phrase_low, 0) + 1
            # Keep max score across seeds
            phrase_to_score[phrase_low] = max(
                phrase_to_score.get(phrase_low, 0.0), float(score)
            )

    # If KeyBERT loaded but produced nothing (all extraction calls failed),
    # also fall back rather than returning an empty bucket.
    if not phrase_to_score:
        print("  [vocab] KeyBERT produced no phrases; falling back to "
              "frequency-based extraction")
        return _fallback_frequency_extract(seed_texts, top_n, ngram_range)

    # Combine score with seed_count: phrases that appear in multiple seeds
    # are more reliable than one-off hits
    candidates = []
    for phrase, score in phrase_to_score.items():
        seed_count = phrase_to_count[phrase]
        # Boost score by seed_count
        boosted = score * (1 + 0.3 * (seed_count - 1))
        candidates.append(CandidatePhrase(
            phrase=phrase, score=boosted, seed_count=seed_count
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_n]


def _fallback_frequency_extract(seed_texts: list[str], top_n: int,
                                ngram_range: tuple[int, int]
                                ) -> list[CandidatePhrase]:
    """Degraded fallback when KeyBERT isn't installed.

    Simple n-gram frequency with stopword filtering. Much worse than
    KeyBERT but better than nothing — gives the LLM curation step
    something to work with.
    """
    # Minimal stopword list (no nltk dependency)
    STOPWORDS = {
        "a", "an", "the", "and", "or", "but", "if", "of", "in", "on", "at",
        "to", "for", "with", "by", "from", "is", "are", "was", "were", "be",
        "been", "being", "as", "this", "that", "these", "those", "we", "our",
        "us", "their", "they", "it", "its", "such", "also", "may", "can",
        "will", "we", "have", "has", "had", "not", "no", "do", "does", "did",
        "but", "than", "then", "so", "more", "most", "much", "however",
    }

    text = " ".join(seed_texts).lower()
    text = re.sub(r"[^\w\s\-]", " ", text)
    tokens = [t for t in text.split() if t and not t.isdigit()]

    counts: dict[str, int] = {}
    n_min, n_max = ngram_range
    for n in range(n_min, n_max + 1):
        for i in range(len(tokens) - n + 1):
            ngram = tokens[i:i + n]
            # Skip if any stopword in the n-gram (for n>1, also skip
            # if it starts/ends with a stopword)
            if n == 1:
                if ngram[0] in STOPWORDS or len(ngram[0]) < 4:
                    continue
            else:
                if ngram[0] in STOPWORDS or ngram[-1] in STOPWORDS:
                    continue
                # skip n-grams where most tokens are stopwords
                if sum(1 for t in ngram if t in STOPWORDS) > 0:
                    continue
            phrase = " ".join(ngram)
            counts[phrase] = counts.get(phrase, 0) + 1

    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [CandidatePhrase(phrase=p, score=float(c), seed_count=1)
            for p, c in items[:top_n]]


# ---------------------------------------------------------------------
# LLM curation
# ---------------------------------------------------------------------

CURATION_SYSTEM_PROMPT = """\
You are a vocabulary curator for a systematic literature review search.

You will be given:
  1. A bucket of candidate phrases extracted from real seed papers in this field
     (via KeyBERT statistical extraction). These are grounded in actual paper text.
  2. The text the phrases were extracted from (so you know the topic).

Your job — strictly editorial, not generative:

  - PICK the strong concept-defining phrases. These are phrases that uniquely
    characterize the topic, that real authors use as terms of art.

  - DROP the weak ones: generic academic vocabulary ("paper", "study", "model",
    "results"), single common words that don't define the topic, fragments,
    duplicates with the strong terms.

  - ADD synonyms ONLY for phrases already in the bucket — when a strong phrase
    has known field-standard synonyms that the bucket happens not to include.
    Example: bucket has "prediction market" → you may add "decision market" and
    "information market" because real papers in this literature use those as
    synonyms. You may NOT add "market" alone, "trading", "geopolitical", or any
    term that is not a synonym of an already-bucketed term. Adding terms from
    general knowledge that aren't synonyms of bucket items is forbidden.

  - GROUP into concept clusters. Each cluster represents one searchable
    "concept" — terms that should be OR'd together in a query. Clusters
    correspond loosely to PICOC slots but you don't need to label them
    P/I/C/O/C; just give them descriptive names.

Hard rules:

  1. Every phrase you output must either appear in the bucket or be a
     direct field-standard synonym of a bucketed phrase. If you find
     yourself reaching for a term that's neither, drop it.

  2. Do not include topic-adjacent vocabulary that broadens the search.
     If the bucket is about prediction markets, do not add "stock market"
     even though it's market-related — it broadens to a different literature.

  3. Output ONLY valid JSON. No prose, no markdown fences.

Output format:

{
  "clusters": [
    {
      "name": "<short descriptive name>",
      "rationale": "<one sentence on why these terms cluster together>",
      "terms": ["term1", "term2", "term3"]
    },
    ...
  ],
  "dropped": ["weak phrase 1", "weak phrase 2"],
  "added_synonyms": ["synonym1 for term in cluster X", ...]
}
"""


def prompt_llm_to_curate(
    keybert_output: list[CandidatePhrase],
    seed_text_summary: str,
    llm_config: dict,
    timeout: int = 120,
) -> dict:
    """Send KeyBERT phrases + seed text to LLM for curation.

    Returns the parsed JSON. Caller is responsible for showing it to the
    user and getting confirmation.
    """
    if not llm_config:
        raise ValueError(
            "LLM config required for vocabulary curation. Set the `llm:` "
            "block in project.yaml."
        )

    provider = llm_config.get("provider")
    model = llm_config.get("model")
    if not provider or not model:
        raise ValueError(
            "llm config needs both 'provider' and 'model'."
        )

    # Build user message
    bucket_lines = []
    for c in keybert_output:
        bucket_lines.append(f"  - {c.phrase} (score={c.score:.2f}, in_seeds={c.seed_count})")
    bucket_str = "\n".join(bucket_lines) if bucket_lines else "  (empty)"

    user_msg = f"""\
## Candidate phrase bucket (from KeyBERT on seed papers)

{bucket_str}

## Seed text summary

{seed_text_summary[:4000]}

## Task

Curate the bucket according to the rules. Output the JSON now.
"""

    raw_response = _llm_call(
        provider=provider,
        model=model,
        system=CURATION_SYSTEM_PROMPT,
        user=user_msg,
        temperature=float(llm_config.get("temperature", 0.0)),
        max_tokens=2048,
        timeout=timeout,
    )

    return _parse_curation_response(raw_response)


def build_vocab_curation_prompt_packet(
    *,
    keybert_output: list[CandidatePhrase],
    seed_text_summary: str,
) -> dict:
    """Return the exact prompt packet for vocabulary curation."""
    bucket_lines = []
    for c in keybert_output:
        bucket_lines.append(f"  - {c.phrase} (score={c.score:.2f}, in_seeds={c.seed_count})")
    bucket_str = "\n".join(bucket_lines) if bucket_lines else "  (empty)"

    user_msg = f"""\
## Candidate phrase bucket (from KeyBERT on seed papers)

{bucket_str}

## Seed text summary

{seed_text_summary[:4000]}

## Task

Curate the bucket according to the rules. Output the JSON now.
"""
    return {
        "task": "vocabulary_curation",
        "system": CURATION_SYSTEM_PROMPT,
        "user": user_msg,
        "response_shape": {
            "clusters": [
                {
                    "name": "<short descriptive name>",
                    "rationale": "<one sentence>",
                    "terms": ["term1", "term2"]
                }
            ],
            "dropped": ["weak phrase"],
            "added_synonyms": ["field-standard synonym"]
        }
    }


def _parse_curation_response(text: str) -> dict:
    """Parse and validate the LLM's curation JSON."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM curation returned invalid JSON: {e}\n"
            f"Got: {text[:300]}"
        )

    if "clusters" not in obj or not isinstance(obj["clusters"], list):
        raise ValueError(
            "LLM curation response missing 'clusters' array. "
            f"Got keys: {list(obj.keys())}"
        )

    # Normalize each cluster
    for cluster in obj["clusters"]:
        if not isinstance(cluster, dict):
            raise ValueError(f"Cluster is not a dict: {cluster}")
        cluster.setdefault("rationale", "")
        if "name" not in cluster or "terms" not in cluster:
            raise ValueError(f"Cluster missing name/terms: {cluster}")
        if not isinstance(cluster["terms"], list):
            raise ValueError(f"Cluster terms not a list: {cluster}")
    obj.setdefault("dropped", [])
    obj.setdefault("added_synonyms", [])
    return obj


# ---------------------------------------------------------------------
# LLM dispatch (mirrors litkit/llm.py providers)
# ---------------------------------------------------------------------

def _llm_call(provider: str, model: str, system: str, user: str,
              temperature: float, max_tokens: int, timeout: int) -> str:
    """Minimal LLM dispatch. Mirrors the providers in litkit/llm.py."""
    if provider == "anthropic":
        return _call_anthropic(model, system, user, temperature, max_tokens, timeout)
    if provider == "deepseek":
        return _call_deepseek(model, system, user, temperature, max_tokens, timeout)
    if provider == "google":
        return _call_google(model, system, user, temperature, max_tokens, timeout)
    raise ValueError(f"Unknown LLM provider: {provider}")


def _call_anthropic(model, system, user, temperature, max_tokens, timeout):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    body = json.dumps({
        "model": model, "max_tokens": max_tokens,
        "temperature": temperature, "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    for b in data.get("content", []):
        if b.get("type") == "text":
            return b["text"]
    raise RuntimeError(f"No text in Anthropic response: {data}")


def _call_deepseek(model, system, user, temperature, max_tokens, timeout):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    body = json.dumps({
        "model": model, "temperature": temperature, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _call_google(model, system, user, temperature, max_tokens, timeout):
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature, "maxOutputTokens": max_tokens,
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
        raise RuntimeError(f"Empty Google response: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"No parts in Google response: {data}")
    return parts[0].get("text", "")


# ---------------------------------------------------------------------
# Helpers for the agent
# ---------------------------------------------------------------------

def build_seed_text_summary(seed_records: list[dict]) -> str:
    """Concatenate seed titles + abstracts into a single string for the LLM
    prompt context. Caller should pass this into prompt_llm_to_curate."""
    parts = []
    for i, rec in enumerate(seed_records, 1):
        if rec.get("error"):
            continue
        parts.append(f"### Seed {i}: {rec.get('title', '(no title)')}")
        if rec.get("year"):
            parts.append(f"Year: {rec['year']}")
        if rec.get("venue"):
            parts.append(f"Venue: {rec['venue']}")
        if rec.get("abstract"):
            parts.append(f"Abstract: {rec['abstract']}")
        if rec.get("keywords"):
            parts.append(f"Keywords: {', '.join(rec['keywords'])}")
        if rec.get("concepts"):
            concept_names = [c["name"] for c in rec["concepts"][:8]
                             if isinstance(c, dict)]
            parts.append(f"OpenAlex concepts: {', '.join(concept_names)}")
        parts.append("")
    return "\n".join(parts)

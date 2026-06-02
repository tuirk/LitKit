"""Post-search sanity check.

Inspects the per-source record counts and a list of "silent failures"
(sources that returned 0 with HTTP errors). Surfaces patterns that
indicate the search is not in a good state to proceed to dedup.

Two-tier:
  - Blocking issues: things that mean dedup would produce a misleading
    result (e.g. zero from primary source with errors). Block.
  - Warnings: things that suggest the search may be off but are not
    catastrophic. Surface, allow override.

The orchestrating script (02_search_open.py) writes these findings to
the events table; the next stage (03_dedup) reads them and refuses to
run unless they were acknowledged.

Thresholds default to conservative values; tune in real use.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Sane defaults — adjustable
TOTAL_TOO_LOW = 30        # below this is too narrow to screen
TOTAL_TOO_HIGH = 5000     # above this is too broad
ASYMMETRY_FACTOR = 10     # one source >10x another flags asymmetric coverage


@dataclass
class SanityResult:
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return bool(self.blocking)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def render(self) -> str:
        lines = []
        if self.blocking:
            lines.append("BLOCKING:")
            for b in self.blocking:
                lines.append(f"  - {b}")
        if self.warnings:
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  - {w}")
        if not self.blocking and not self.warnings:
            lines.append("ok — counts look reasonable")
        return "\n".join(lines)


def check_post_search(
    counts: dict[str, int],
    silent_failures: list[str],
    max_records_cap: int = 2000,
    primary_source: str = "openalex",
) -> SanityResult:
    """Run all sanity checks. Returns aggregated result."""
    r = SanityResult()
    total = sum(counts.values())

    # 1. Silent failures: 0 records with errors logged
    for src in silent_failures:
        r.blocking.append(
            f"{src}: returned 0 records but had HTTP errors during the run "
            f"— likely network/API failure, not a real null result. "
            f"Investigate before proceeding."
        )

    # 2. Zero from primary source (without already being a silent failure)
    primary_count = counts.get(primary_source)
    if (primary_count is not None and primary_count == 0
            and primary_source not in silent_failures):
        r.blocking.append(
            f"{primary_source} returned 0 records (no HTTP errors). For most "
            "topics in academic literature, the primary source returning "
            "zero is a sign the query is malformed or so narrow nothing "
            "matches. Verify the query before continuing."
        )

    # 3. Cap-hit: any source returned exactly the engine's pagination cap
    for src, n in counts.items():
        if n == max_records_cap:
            r.warnings.append(
                f"{src}: returned exactly {n} records, which is the engine's "
                f"max_records cap. Real result set is likely larger; what "
                "you have is the top-relevance slice. Consider tightening "
                "the query or raising --max-records."
            )

    # 4. Total below useful threshold
    if 0 < total < TOTAL_TOO_LOW:
        r.warnings.append(
            f"total {total} records is below useful screening volume "
            f"({TOTAL_TOO_LOW} threshold). Likely query is too narrow. "
            "Consider widening synonyms or removing constraints."
        )

    # 5. Total way above target
    if total > TOTAL_TOO_HIGH:
        r.warnings.append(
            f"total {total} records is well above the typical 200-2000 "
            "target. Likely query is too broad. Consider tightening — "
            "screening 5000+ records is rarely productive."
        )

    # 6. Asymmetric coverage between two sources that both ran
    nonzero = {s: n for s, n in counts.items() if n > 0}
    if len(nonzero) >= 2:
        max_src, max_n = max(nonzero.items(), key=lambda kv: kv[1])
        min_src, min_n = min(nonzero.items(), key=lambda kv: kv[1])
        if min_n > 0 and max_n / min_n >= ASYMMETRY_FACTOR:
            r.warnings.append(
                f"asymmetric coverage: {max_src}={max_n} vs {min_src}={min_n} "
                f"(ratio {max_n // min_n}x). Likely one query is too broad "
                "or another too narrow. Compare structures and tighten."
            )

    return r

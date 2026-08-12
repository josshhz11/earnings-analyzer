"""Faithfulness check — fully programmatic, no LLM call.

For every claim, verifies its `source_quote` actually appears in the transcript
turn it cites — with only whitespace/minor-punctuation normalization, not fuzzy
matching. This is a more thorough, standalone re-check than the exact-substring
gate already applied inside `src/extraction/claim_extractor.py` (which drops
unverifiable claims before they're even returned); running it again here, as
its own auditable stage with its own report, is what makes "faithfulness rate"
a real, inspectable number in the eval report rather than an assumption baked
into extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.extraction.claim_extractor import ExtractedClaim
from src.ingestion.segmentation import Turn

# Unicode punctuation variants seen in real transcript PDFs (curly quotes,
# multiple dash widths) that should not cause a spurious faithfulness failure
# — normalized to their ASCII equivalents before comparison, alongside
# whitespace collapsing. This is intentionally narrow: it does not fix
# genuine paraphrasing, only cosmetic character differences.
_PUNCTUATION_NORMALIZATION = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
}

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    for variant, ascii_equivalent in _PUNCTUATION_NORMALIZATION.items():
        text = text.replace(variant, ascii_equivalent)
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True)
class FaithfulnessResult:
    """Faithfulness verdict for a single claim."""

    claim_text: str
    source_turn_number: int
    passed: bool
    reason: str = ""  # populated only when passed is False


@dataclass(frozen=True)
class FaithfulnessReport:
    results: tuple[FaithfulnessResult, ...]
    total: int
    passed_count: int
    failed_count: int
    faithfulness_rate: float  # passed_count / total; 1.0 when total == 0


def check_faithfulness(
    claims: list[ExtractedClaim], turns: list[Turn]
) -> FaithfulnessReport:
    """Verify every claim's source_quote against its cited transcript turn.

    A claim passes if its source_turn_number resolves to a real turn AND its
    source_quote (normalized — see `_normalize`) is a substring of that
    turn's (normalized) text. Everything else fails, with a `reason`.
    """
    turns_by_number = {t.turn_number: t for t in turns}
    results: list[FaithfulnessResult] = []

    for claim in claims:
        turn = turns_by_number.get(claim.source_turn_number)
        if turn is None:
            results.append(
                FaithfulnessResult(
                    claim_text=claim.claim_text,
                    source_turn_number=claim.source_turn_number,
                    passed=False,
                    reason=f"source_turn_number {claim.source_turn_number} does not exist in the transcript",
                )
            )
            continue

        if _normalize(claim.source_quote) in _normalize(turn.text):
            results.append(
                FaithfulnessResult(
                    claim_text=claim.claim_text,
                    source_turn_number=claim.source_turn_number,
                    passed=True,
                )
            )
        else:
            results.append(
                FaithfulnessResult(
                    claim_text=claim.claim_text,
                    source_turn_number=claim.source_turn_number,
                    passed=False,
                    reason="source_quote not found (even after whitespace/punctuation "
                    f"normalization) in turn {claim.source_turn_number}'s text",
                )
            )

    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    failed_count = total - passed_count
    faithfulness_rate = (passed_count / total) if total else 1.0

    return FaithfulnessReport(
        results=tuple(results),
        total=total,
        passed_count=passed_count,
        failed_count=failed_count,
        faithfulness_rate=faithfulness_rate,
    )

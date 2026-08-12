"""Coverage check — fully programmatic, no LLM call.

Confirms every transcript section that actually exists in the source (some
transcripts have no Q&A — see segmentation.py's low_confidence path) produced
at least one extracted claim. Flags a section as silently skipped only when it
was present in the transcript but claims cite zero turns from it — this is
different from "the transcript never had a Q&A section," which is not a
coverage failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.extraction.claim_extractor import ExtractedClaim
from src.ingestion.segmentation import Turn


@dataclass(frozen=True)
class CoverageReport:
    sections_present: tuple[str, ...]  # sections that actually exist in the transcript
    sections_with_claims: tuple[str, ...]  # of those, which produced at least one claim
    sections_missing_claims: tuple[str, ...]  # present but zero claims — the flag
    passed: bool  # True iff sections_missing_claims is empty


def check_coverage(claims: list[ExtractedClaim], turns: list[Turn]) -> CoverageReport:
    """Check that every section present in the transcript produced claims.

    A section counts as "present" if at least one turn belongs to it — not
    every transcript has a Q&A section (see segmentation.py's boundary-
    detection fallbacks), and a transcript with no Q&A turns at all should
    not be flagged for having zero Q&A claims.
    """
    sections_present = tuple(dict.fromkeys(t.section for t in turns))

    turn_section_by_number = {t.turn_number: t.section for t in turns}
    sections_with_claims_set = {
        turn_section_by_number[c.source_turn_number]
        for c in claims
        if c.source_turn_number in turn_section_by_number
    }
    sections_with_claims = tuple(s for s in sections_present if s in sections_with_claims_set)
    sections_missing_claims = tuple(
        s for s in sections_present if s not in sections_with_claims_set
    )

    return CoverageReport(
        sections_present=sections_present,
        sections_with_claims=sections_with_claims,
        sections_missing_claims=sections_missing_claims,
        passed=len(sections_missing_claims) == 0,
    )

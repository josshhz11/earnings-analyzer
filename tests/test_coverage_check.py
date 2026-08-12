"""Tests for src.eval.coverage_check — fully deterministic, no API calls."""

from src.eval.coverage_check import check_coverage
from src.extraction.claim_extractor import ExtractedClaim
from src.ingestion.segmentation import PREPARED_REMARKS, QA, Turn

PREPARED_TURN = Turn(
    turn_number=1,
    speaker_name="A",
    speaker_title=None,
    section=PREPARED_REMARKS,
    text="prepared remarks text",
)
QA_TURN = Turn(
    turn_number=2,
    speaker_name="B",
    speaker_title=None,
    section=QA,
    text="qa text",
)


def _claim(source_turn_number):
    return ExtractedClaim(
        claim_text="a claim",
        category="financial_performance",
        source_turn_number=source_turn_number,
        source_quote="text",
        confidence_flag=False,
    )


def test_both_sections_covered_passes():
    report = check_coverage([_claim(1), _claim(2)], [PREPARED_TURN, QA_TURN])
    assert report.sections_present == (PREPARED_REMARKS, QA)
    assert set(report.sections_with_claims) == {PREPARED_REMARKS, QA}
    assert report.sections_missing_claims == ()
    assert report.passed is True


def test_qa_section_present_but_no_claims_is_flagged():
    report = check_coverage([_claim(1)], [PREPARED_TURN, QA_TURN])
    assert report.sections_missing_claims == (QA,)
    assert report.passed is False


def test_transcript_with_no_qa_section_is_not_flagged_for_missing_qa():
    # No QA turns at all in the source — this is not a coverage failure.
    report = check_coverage([_claim(1)], [PREPARED_TURN])
    assert report.sections_present == (PREPARED_REMARKS,)
    assert report.sections_missing_claims == ()
    assert report.passed is True


def test_empty_claims_with_both_sections_present_flags_both():
    report = check_coverage([], [PREPARED_TURN, QA_TURN])
    assert set(report.sections_missing_claims) == {PREPARED_REMARKS, QA}
    assert report.passed is False


def test_claim_citing_nonexistent_turn_does_not_count_toward_coverage():
    report = check_coverage([_claim(999)], [PREPARED_TURN, QA_TURN])
    assert report.sections_missing_claims == (PREPARED_REMARKS, QA)
    assert report.passed is False

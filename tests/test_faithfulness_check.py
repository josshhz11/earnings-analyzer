"""Tests for src.eval.faithfulness_check — fully deterministic, no API calls."""

from src.eval.faithfulness_check import check_faithfulness
from src.extraction.claim_extractor import ExtractedClaim
from src.ingestion.segmentation import PREPARED_REMARKS, Turn

TURN_1 = Turn(
    turn_number=1,
    speaker_name="Mark Zuckerberg",
    speaker_title="CEO",
    section=PREPARED_REMARKS,
    text="Q4 total revenue was $48.4 billion, up 21% on both a reported and constant currency basis.",
)


def _claim(source_quote, source_turn_number=1, claim_text="a claim"):
    return ExtractedClaim(
        claim_text=claim_text,
        category="financial_performance",
        source_turn_number=source_turn_number,
        source_quote=source_quote,
        confidence_flag=False,
    )


def test_exact_quote_passes():
    report = check_faithfulness([_claim("Q4 total revenue was $48.4 billion")], [TURN_1])
    assert report.passed_count == 1
    assert report.failed_count == 0
    assert report.faithfulness_rate == 1.0
    assert report.results[0].passed is True


def test_paraphrased_quote_fails():
    report = check_faithfulness(
        [_claim("revenue was way up, higher than analysts expected")], [TURN_1]
    )
    assert report.passed_count == 0
    assert report.failed_count == 1
    assert report.faithfulness_rate == 0.0
    assert report.results[0].passed is False
    assert "not found" in report.results[0].reason


def test_nonexistent_turn_fails_with_specific_reason():
    report = check_faithfulness([_claim("Q4 total revenue", source_turn_number=99)], [TURN_1])
    assert report.results[0].passed is False
    assert "does not exist" in report.results[0].reason


def test_whitespace_differences_are_normalized():
    turn = Turn(
        turn_number=2,
        speaker_name="X",
        speaker_title=None,
        section=PREPARED_REMARKS,
        text="Revenue   grew\n  20%   year over year.",
    )
    report = check_faithfulness(
        [_claim("Revenue grew 20% year over year.", source_turn_number=2)], [turn]
    )
    assert report.results[0].passed is True


def test_unicode_punctuation_variants_are_normalized():
    turn = Turn(
        turn_number=3,
        speaker_name="X",
        speaker_title=None,
        section=PREPARED_REMARKS,
        text="We saw double‐digit growth and management said “we’re pleased.”",
    )
    claim = _claim('We saw double-digit growth and management said "we\'re pleased."', source_turn_number=3)
    report = check_faithfulness([claim], [turn])
    assert report.results[0].passed is True


def test_empty_claims_list_gives_perfect_rate():
    report = check_faithfulness([], [TURN_1])
    assert report.total == 0
    assert report.faithfulness_rate == 1.0


def test_mixed_pass_and_fail_rate_computed_correctly():
    claims = [
        _claim("Q4 total revenue was $48.4 billion"),  # passes
        _claim("this text is nowhere in the transcript"),  # fails
    ]
    report = check_faithfulness(claims, [TURN_1])
    assert report.total == 2
    assert report.passed_count == 1
    assert report.failed_count == 1
    assert report.faithfulness_rate == 0.5

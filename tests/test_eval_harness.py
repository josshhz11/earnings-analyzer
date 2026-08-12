"""Tests for src.eval.eval_harness — orchestration of all three checks."""

from types import SimpleNamespace

from src.eval.eval_harness import run_eval
from src.extraction.claim_extractor import ExtractedClaim
from src.ingestion.segmentation import PREPARED_REMARKS, QA, Turn

PREPARED_TURN = Turn(
    turn_number=1,
    speaker_name="A",
    speaker_title=None,
    section=PREPARED_REMARKS,
    text="Q4 total revenue was $48.4 billion. We face headwinds in the EU and the US.",
)
QA_TURN = Turn(
    turn_number=2,
    speaker_name="B",
    speaker_title=None,
    section=QA,
    text="We expect continued growth next year.",
)

FINANCIAL_CLAIM = ExtractedClaim(
    claim_text="Q4 revenue was $48.4 billion.",
    category="financial_performance",
    source_turn_number=1,
    source_quote="Q4 total revenue was $48.4 billion",
    confidence_flag=False,
)
RISK_CLAIM = ExtractedClaim(
    claim_text="Meta faces regulatory headwinds in the EU and US.",
    category="risk_factors",
    source_turn_number=1,
    source_quote="headwinds in the EU and the US",
    confidence_flag=False,
)
QA_CLAIM = ExtractedClaim(
    claim_text="Growth is expected to continue next year.",
    category="guidance",
    source_turn_number=2,
    source_quote="We expect continued growth next year",
    confidence_flag=False,
)


class _FakeMessages:
    def __init__(self, score_sequence):
        self._scores = list(score_sequence)
        self.call_count = 0

    def parse(self, **kwargs):
        self.call_count += 1
        score = self._scores[self.call_count - 1]
        parsed = SimpleNamespace(score=score, rationale="because")
        usage = SimpleNamespace(
            input_tokens=50, output_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return SimpleNamespace(parsed_output=parsed, usage=usage, stop_reason="end_turn")


class _FakeClient:
    def __init__(self, score_sequence):
        self.messages = _FakeMessages(score_sequence)


class _PoisonClient:
    """Raises if `.messages` is ever accessed — proves run_eval skips the API
    entirely when there are no judgment-call claims to assess."""

    @property
    def messages(self):
        raise AssertionError("client.messages accessed with no judgment-call claims present")


def test_run_eval_combines_all_three_checks():
    claims = [FINANCIAL_CLAIM, RISK_CLAIM, QA_CLAIM]
    client = _FakeClient([3, 3])  # agreeing samples for the one risk_factors claim

    report = run_eval(claims, [PREPARED_TURN, QA_TURN], client=client)

    assert report.faithfulness.total == 3
    assert report.faithfulness.passed_count == 3
    assert report.coverage.passed is True
    assert len(report.consistency) == 1
    assert report.consistency[0].category == "risk_factors"
    assert report.consistency[0].stable is True
    assert len(report.usage) == 2
    assert client.messages.call_count == 2


def test_run_eval_skips_api_entirely_with_no_judgment_claims():
    claims = [FINANCIAL_CLAIM, QA_CLAIM]  # no risk_factors / hedging_tone claims

    report = run_eval(claims, [PREPARED_TURN, QA_TURN], client=_PoisonClient())

    assert report.consistency == ()
    assert report.usage == ()
    assert report.faithfulness.passed_count == 2
    assert report.coverage.passed is True


def test_run_eval_flags_unfaithful_and_uncovered_claims_together():
    corrupted_risk_claim = ExtractedClaim(
        claim_text=RISK_CLAIM.claim_text,
        category=RISK_CLAIM.category,
        source_turn_number=RISK_CLAIM.source_turn_number,
        source_quote="this quote was deliberately corrupted and is not in the transcript",
        confidence_flag=False,
    )
    client = _FakeClient([3, 3])

    # Only cite Prepared Remarks turns -> Q&A section should be flagged as
    # missing claims even though it exists in the transcript.
    report = run_eval([FINANCIAL_CLAIM, corrupted_risk_claim], [PREPARED_TURN, QA_TURN], client=client)

    assert report.faithfulness.passed_count == 1
    assert report.faithfulness.failed_count == 1
    assert report.faithfulness.results[1].passed is False
    assert report.coverage.passed is False
    assert report.coverage.sections_missing_claims == (QA,)
    # The corrupted claim's category is still a judgment-call category, so
    # consistency checking still runs on it — faithfulness and consistency
    # are independent checks, deliberately not gated on each other.
    assert len(report.consistency) == 1

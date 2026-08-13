"""Tests for src.revision.reviser — no real API calls (fake client)."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from src.eval.consistency_check import ConsistencyResult
from src.eval.eval_harness import EvalReport
from src.eval.faithfulness_check import FaithfulnessReport, FaithfulnessResult
from src.extraction.claim_extractor import ExtractedClaim
from src.ingestion.segmentation import PREPARED_REMARKS, Turn
from src.revision.reviser import (
    HIGH_VARIANCE_RANGE_THRESHOLD,
    REVISION_MODEL,
    RevisionError,
    _CorrectedClaim,
    _DiscardedClaim,
    revise_claims,
)

TURN_1 = Turn(
    turn_number=1,
    speaker_name="Mark Zuckerberg",
    speaker_title="CEO",
    section=PREPARED_REMARKS,
    text="Q4 total revenue was $48.4 billion, up 21%. We face headwinds in the EU and the US.",
)

GOOD_CLAIM = ExtractedClaim(
    claim_text="Q4 revenue was $48.4 billion.",
    category="financial_performance",
    source_turn_number=1,
    source_quote="Q4 total revenue was $48.4 billion",
    confidence_flag=False,
)
UNFAITHFUL_CLAIM = ExtractedClaim(
    claim_text="Revenue tripled year over year.",
    category="financial_performance",
    source_turn_number=1,
    source_quote="revenue absolutely exploded beyond all expectations",  # not in TURN_1
    confidence_flag=False,
)
RISK_CLAIM = ExtractedClaim(
    claim_text="Meta faces regulatory headwinds in the EU and US.",
    category="risk_factors",
    source_turn_number=1,
    source_quote="headwinds in the EU and the US",
    confidence_flag=False,
)
NONEXISTENT_TURN_CLAIM = ExtractedClaim(
    claim_text="Some claim.",
    category="financial_performance",
    source_turn_number=99,
    source_quote="anything",
    confidence_flag=False,
)


def _faithfulness_report(claims, unfaithful_indices=()):
    results = []
    for i, c in enumerate(claims):
        if i in unfaithful_indices:
            results.append(
                FaithfulnessResult(
                    claim_text=c.claim_text,
                    source_turn_number=c.source_turn_number,
                    passed=False,
                    reason="source_quote not found",
                )
            )
        else:
            results.append(
                FaithfulnessResult(
                    claim_text=c.claim_text, source_turn_number=c.source_turn_number, passed=True
                )
            )
    passed_count = sum(r.passed for r in results)
    return FaithfulnessReport(
        results=tuple(results),
        total=len(results),
        passed_count=passed_count,
        failed_count=len(results) - passed_count,
        faithfulness_rate=(passed_count / len(results)) if results else 1.0,
    )


def _eval_report(claims, unfaithful_indices=(), consistency=()):
    return EvalReport(
        faithfulness=_faithfulness_report(claims, unfaithful_indices),
        coverage=SimpleNamespace(passed=True),  # not exercised by reviser
        consistency=tuple(consistency),
        usage=(),
    )


class _FakeMessages:
    def __init__(self, results):
        self._results = list(results)
        self.call_count = 0
        self.last_call_kwargs = None

    def parse(self, **kwargs):
        self.call_count += 1
        self.last_call_kwargs = kwargs
        result = self._results[self.call_count - 1]
        parsed = SimpleNamespace(result=result)
        usage = SimpleNamespace(
            input_tokens=200, output_tokens=80, cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return SimpleNamespace(parsed_output=parsed, usage=usage, stop_reason="end_turn")


class _FakeClient:
    def __init__(self, results):
        self.messages = _FakeMessages(results)


class _PoisonClient:
    @property
    def messages(self):
        raise AssertionError("client.messages accessed when no API call should be needed")


# --- Core targeted-revision behavior -----------------------------------------


def test_no_flagged_claims_makes_no_api_call_and_returns_claims_unchanged():
    claims = [GOOD_CLAIM]
    report = _eval_report(claims)

    result = revise_claims(claims, report, [TURN_1], client=_PoisonClient())

    assert result.revised_claims == tuple(claims)
    assert result.outcomes == ()
    assert result.usage == ()
    assert result.post_revision_faithfulness.faithfulness_rate == 1.0


def test_unfaithful_claim_gets_corrected_and_replaces_original():
    claims = [GOOD_CLAIM, UNFAITHFUL_CLAIM]
    report = _eval_report(claims, unfaithful_indices={1})
    corrected = _CorrectedClaim(
        action="corrected",
        claim_text="Q4 revenue was up 21% year over year.",
        category="financial_performance",
        source_quote="Q4 total revenue was $48.4 billion, up 21%",
        confidence_flag=False,
        reasoning="The original quote wasn't verbatim; corrected to what the turn actually says.",
    )
    client = _FakeClient([corrected])

    result = revise_claims(claims, report, [TURN_1], client=client)

    assert client.messages.call_count == 1
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.original_claim == UNFAITHFUL_CLAIM
    assert outcome.action == "corrected"
    assert outcome.revised_claim.claim_text == corrected.claim_text
    assert outcome.revised_claim.source_turn_number == 1  # unchanged — no re-attribution
    # Untouched claim stays, corrected claim replaces the original.
    assert GOOD_CLAIM in result.revised_claims
    assert UNFAITHFUL_CLAIM not in result.revised_claims
    assert outcome.revised_claim in result.revised_claims


def test_post_revision_faithfulness_confirms_the_fix_actually_worked():
    claims = [UNFAITHFUL_CLAIM]
    report = _eval_report(claims, unfaithful_indices={0})
    corrected = _CorrectedClaim(
        action="corrected",
        claim_text="Q4 revenue was up 21%.",
        category="financial_performance",
        source_quote="Q4 total revenue was $48.4 billion, up 21%",  # genuinely verbatim in TURN_1
        confidence_flag=False,
        reasoning="Corrected to a verbatim quote.",
    )
    client = _FakeClient([corrected])

    result = revise_claims(claims, report, [TURN_1], client=client)

    assert result.post_revision_faithfulness.faithfulness_rate == 1.0
    assert result.post_revision_faithfulness.failed_count == 0


def test_discarded_claim_is_removed_from_revised_claims():
    claims = [GOOD_CLAIM, UNFAITHFUL_CLAIM]
    report = _eval_report(claims, unfaithful_indices={1})
    discard = _DiscardedClaim(action="discard", reasoning="No supportable claim in this turn.")
    client = _FakeClient([discard])

    result = revise_claims(claims, report, [TURN_1], client=client)

    assert result.outcomes[0].action == "discard"
    assert result.outcomes[0].revised_claim is None
    assert result.revised_claims == (GOOD_CLAIM,)


def test_claim_flagged_by_both_checks_gets_one_combined_revision_call():
    claims = [RISK_CLAIM]
    consistency = [
        ConsistencyResult(
            claim_text=RISK_CLAIM.claim_text,
            category="risk_factors",
            dimension="materiality",
            samples=(1, 5, 2, 4, 5),
            median=4,
            range_low=1,
            range_high=5,
            stable=False,
            escalated=True,
        )
    ]
    report = _eval_report(claims, unfaithful_indices={0}, consistency=consistency)
    corrected = _CorrectedClaim(
        action="corrected",
        claim_text="Meta faces regulatory headwinds.",
        category="risk_factors",
        source_quote="headwinds in the EU and the US",
        confidence_flag=False,
        reasoning="Fixed quote and reconsidered materiality framing.",
    )
    client = _FakeClient([corrected])

    result = revise_claims(claims, report, [TURN_1], client=client)

    assert client.messages.call_count == 1  # one call, not two
    assert set(result.outcomes[0].reasons) == {"unfaithful_quote", "high_variance_judgment"}


# --- High-variance judgment-call triggering ----------------------------------


@pytest.mark.parametrize(
    "escalated,range_low,range_high,should_trigger",
    [
        (True, 1, 5, True),  # escalated, wide spread -> revise
        (True, 3, 4, False),  # escalated, but narrow final spread -> don't revise
        (False, 3, 4, False),  # never escalated (agreed at N=2) -> don't revise
    ],
)
def test_high_variance_triggering_rules(escalated, range_low, range_high, should_trigger):
    claims = [RISK_CLAIM]
    consistency = [
        ConsistencyResult(
            claim_text=RISK_CLAIM.claim_text,
            category="risk_factors",
            dimension="materiality",
            samples=(range_low, range_high),
            median=(range_low + range_high) / 2,
            range_low=range_low,
            range_high=range_high,
            stable=not escalated,
            escalated=escalated,
        )
    ]
    report = _eval_report(claims, consistency=consistency)

    if should_trigger:
        corrected = _CorrectedClaim(
            action="corrected",
            claim_text=RISK_CLAIM.claim_text,
            category="risk_factors",
            source_quote=RISK_CLAIM.source_quote,
            confidence_flag=False,
            reasoning="Reconsidered.",
        )
        client = _FakeClient([corrected])
        result = revise_claims(claims, report, [TURN_1], client=client)
        assert client.messages.call_count == 1
    else:
        result = revise_claims(claims, report, [TURN_1], client=_PoisonClient())
        assert result.outcomes == ()


def test_high_variance_range_threshold_is_configurable():
    claims = [RISK_CLAIM]
    consistency = [
        ConsistencyResult(
            claim_text=RISK_CLAIM.claim_text,
            category="risk_factors",
            dimension="materiality",
            samples=(2, 4, 2, 3, 3),
            median=3,
            range_low=2,
            range_high=4,  # spread of 2
            stable=False,
            escalated=True,
        )
    ]
    report = _eval_report(claims, consistency=consistency)

    # With a stricter threshold (3), a spread of 2 shouldn't trigger revision.
    result = revise_claims(
        claims, report, [TURN_1], client=_PoisonClient(), high_variance_range_threshold=3
    )
    assert result.outcomes == ()
    assert HIGH_VARIANCE_RANGE_THRESHOLD == 2  # confirms the module default wasn't mutated


# --- Nonexistent-turn claims: auto-discard, no wasted API call --------------


def test_claim_citing_nonexistent_turn_is_auto_discarded_without_an_api_call():
    claims = [NONEXISTENT_TURN_CLAIM]
    report = _eval_report(claims, unfaithful_indices={0})

    result = revise_claims(claims, report, [TURN_1], client=_PoisonClient())

    assert result.outcomes[0].action == "discard"
    assert "does not exist" in result.outcomes[0].model_reasoning
    assert result.revised_claims == ()


# --- Usage logging (Phase 2 cost-instrumentation prep) -----------------------


def test_usage_logger_called_once_per_revision_call():
    claims = [UNFAITHFUL_CLAIM]
    report = _eval_report(claims, unfaithful_indices={0})
    corrected = _CorrectedClaim(
        action="corrected",
        claim_text="x",
        category="financial_performance",
        source_quote="Q4 total revenue was $48.4 billion",
        confidence_flag=False,
        reasoning="r",
    )
    client = _FakeClient([corrected])
    logged = []

    revise_claims(claims, report, [TURN_1], client=client, usage_logger=logged.append)

    assert len(logged) == 1
    assert logged[0].stage == "revision"
    assert logged[0].model == REVISION_MODEL


# --- Request validation and failure handling ---------------------------------


def test_mismatched_eval_report_raises_value_error():
    claims = [GOOD_CLAIM, UNFAITHFUL_CLAIM]
    report = _eval_report([GOOD_CLAIM])  # only 1 result for 2 claims

    with pytest.raises(ValueError, match="doesn't match claims"):
        revise_claims(claims, report, [TURN_1], client=_PoisonClient())


def test_refusal_raises_revision_error():
    claims = [UNFAITHFUL_CLAIM]
    report = _eval_report(claims, unfaithful_indices={0})

    class _RefusalMessages:
        def parse(self, **kwargs):
            usage = SimpleNamespace(
                input_tokens=10, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(parsed_output=None, usage=usage, stop_reason="refusal")

    client = SimpleNamespace(messages=_RefusalMessages())
    with pytest.raises(RevisionError, match="refusal"):
        revise_claims(claims, report, [TURN_1], client=client)


class _TinyModel(BaseModel):
    result: dict


def test_truncated_json_response_raises_revision_error():
    claims = [UNFAITHFUL_CLAIM]
    report = _eval_report(claims, unfaithful_indices={0})

    class _TruncatedMessages:
        def parse(self, **kwargs):
            _TinyModel.model_validate_json('{"result": {"action": "corr')

    client = SimpleNamespace(messages=_TruncatedMessages())

    with pytest.raises(RevisionError, match="truncated") as exc_info:
        revise_claims(claims, report, [TURN_1], client=client)
    assert isinstance(exc_info.value.__cause__, ValidationError)

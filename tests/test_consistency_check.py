"""Tests for src.eval.consistency_check — no real API calls (fake client)."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from src.eval.consistency_check import (
    AGREEMENT_THRESHOLD,
    JUDGMENT_MODEL,
    ConsistencyCheckError,
    assess_consistency,
)
from src.extraction.claim_extractor import ExtractedClaim


def _claim(category="risk_factors", claim_text="Regulatory headwinds could hurt results."):
    return ExtractedClaim(
        claim_text=claim_text,
        category=category,
        source_turn_number=1,
        source_quote="headwinds in the EU and the US",
        confidence_flag=False,
    )


class _FakeMessages:
    """Returns the next score in `score_sequence` on each call, in order."""

    def __init__(self, score_sequence):
        self._scores = list(score_sequence)
        self.call_count = 0
        self.last_call_kwargs = None

    def parse(self, **kwargs):
        self.call_count += 1
        self.last_call_kwargs = kwargs
        score = self._scores[self.call_count - 1]
        parsed = SimpleNamespace(score=score, rationale="because reasons")
        usage = SimpleNamespace(
            input_tokens=50, output_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return SimpleNamespace(parsed_output=parsed, usage=usage, stop_reason="end_turn")


class _FakeClient:
    def __init__(self, score_sequence):
        self.messages = _FakeMessages(score_sequence)


# --- Adaptive sampling core logic -------------------------------------------


def test_agreeing_samples_stop_at_two_and_report_stable():
    client = _FakeClient([3, 3])
    result, usages = assess_consistency(_claim(), client=client)

    assert client.messages.call_count == 2
    assert result.samples == (3, 3)
    assert result.stable is True
    assert result.escalated is False
    assert result.median == 3.0
    assert result.range_low == 3
    assert result.range_high == 3
    assert len(usages) == 2


def test_samples_within_threshold_still_count_as_agreeing():
    # AGREEMENT_THRESHOLD is 1 — a difference of exactly 1 should still stop at N=2.
    client = _FakeClient([3, 4])
    result, _ = assess_consistency(_claim(), client=client)

    assert client.messages.call_count == 2
    assert result.stable is True
    assert abs(result.samples[0] - result.samples[1]) == AGREEMENT_THRESHOLD


def test_disagreeing_samples_escalate_to_five_and_report_median_and_range():
    client = _FakeClient([1, 5, 3, 3, 4])
    result, usages = assess_consistency(_claim(), client=client)

    assert client.messages.call_count == 5
    assert result.samples == (1, 5, 3, 3, 4)
    assert result.stable is False
    assert result.escalated is True
    assert result.median == 3  # statistics.median([1,5,3,3,4]) == 3
    assert result.range_low == 1
    assert result.range_high == 5
    assert len(usages) == 5


# --- Category validation -----------------------------------------------------


def test_non_judgment_category_raises_value_error():
    client = _FakeClient([3, 3])
    with pytest.raises(ValueError, match="non-judgment-call category"):
        assess_consistency(_claim(category="financial_performance"), client=client)


@pytest.mark.parametrize(
    "category,expected_dimension",
    [("risk_factors", "materiality"), ("hedging_tone", "framing")],
)
def test_dimension_mapping_per_category(category, expected_dimension):
    client = _FakeClient([3, 3])
    result, _ = assess_consistency(_claim(category=category), client=client)
    assert result.dimension == expected_dimension


# --- Usage logging (Phase 2 cost-instrumentation prep) -----------------------


def test_usage_logger_called_once_per_sample():
    client = _FakeClient([1, 5, 3, 3, 4])  # escalates to 5 samples
    logged = []

    assess_consistency(_claim(), client=client, usage_logger=logged.append)

    assert len(logged) == 5
    assert all(u.stage == "eval_consistency" for u in logged)
    assert all(u.model == JUDGMENT_MODEL for u in logged)


# --- Request shape ------------------------------------------------------------


def test_request_uses_judgment_model_and_dimension_specific_system_prompt():
    client = _FakeClient([3, 3])
    assess_consistency(_claim(category="hedging_tone"), client=client)

    kwargs = client.messages.last_call_kwargs
    assert kwargs["model"] == JUDGMENT_MODEL
    assert "hedged" in kwargs["system"].lower()
    assert "confident" in kwargs["system"].lower()
    # Thinking is on by default on claude-opus-5 and max_tokens caps thinking
    # + answer together — disabled here so a small max_tokens can't starve
    # the answer text (see KNOWN_ISSUES.md for the live-tested failure mode).
    assert kwargs["thinking"] == {"type": "disabled"}


# --- Failure handling ---------------------------------------------------------


def test_refusal_raises_consistency_check_error():
    class _RefusalMessages:
        def parse(self, **kwargs):
            usage = SimpleNamespace(
                input_tokens=10, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(parsed_output=None, usage=usage, stop_reason="refusal")

    client = SimpleNamespace(messages=_RefusalMessages())
    with pytest.raises(ConsistencyCheckError, match="refusal"):
        assess_consistency(_claim(), client=client)


class _TinyModel(BaseModel):
    score: int


def test_truncated_json_response_raises_consistency_check_error():
    class _TruncatedMessages:
        def parse(self, **kwargs):
            _TinyModel.model_validate_json('{"score": 3')  # incomplete JSON

    client = SimpleNamespace(messages=_TruncatedMessages())

    with pytest.raises(ConsistencyCheckError, match="truncated") as exc_info:
        assess_consistency(_claim(), client=client)
    assert isinstance(exc_info.value.__cause__, ValidationError)

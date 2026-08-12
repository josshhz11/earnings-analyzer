"""Tests for src.extraction.claim_extractor — claim extraction + verification.

No real API calls: a fake Anthropic client stands in for `client.messages.parse`,
so these tests exercise the wiring (system prompt construction, request shape,
usage tagging, and — most importantly — the programmatic source_quote
verification) without needing credentials. There is no live-API test in this
suite; see memory/STATE.md for why (no ANTHROPIC_API_KEY configured in this
dev environment) and what running one requires.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from src.extraction.claim_extractor import (
    CATEGORY_VALUES,
    DEFAULT_MODEL,
    STAGE,
    ClaimExtractionError,
    _build_user_message,
    _load_system_prompt,
    extract_claims,
)
from src.ingestion.segmentation import PREPARED_REMARKS, QA, Turn

TURN_1 = Turn(
    turn_number=1,
    speaker_name="Mark Zuckerberg",
    speaker_title="CEO",
    section=PREPARED_REMARKS,
    text="Q4 total revenue was $48.4 billion, up 21% on both a reported and constant currency basis.",
)
TURN_2 = Turn(
    turn_number=2,
    speaker_name="Brian Nowak",
    speaker_title=None,
    section=QA,
    text="We expect this momentum to continue into next year.",
)


def _fake_claim(
    claim_text="Q4 revenue was $48.4 billion.",
    category="financial_performance",
    source_turn_number=1,
    source_quote="Q4 total revenue was $48.4 billion",
    confidence_flag=False,
):
    return SimpleNamespace(
        claim_text=claim_text,
        category=category,
        source_turn_number=source_turn_number,
        source_quote=source_quote,
        confidence_flag=confidence_flag,
    )


def _fake_response(claims, stop_reason="end_turn", input_tokens=100, output_tokens=50):
    parsed_output = SimpleNamespace(claims=claims) if stop_reason != "refusal_no_output" else None
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    return SimpleNamespace(
        parsed_output=parsed_output,
        usage=usage,
        stop_reason="refusal" if stop_reason == "refusal_no_output" else stop_reason,
    )


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.last_call_kwargs = None
        self.call_count = 0

    def parse(self, **kwargs):
        self.call_count += 1
        self.last_call_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


class _NeverCalledMessages:
    def parse(self, **kwargs):
        raise AssertionError("messages.parse should not be called for empty input")


class _NeverCalledClient:
    def __init__(self):
        self.messages = _NeverCalledMessages()


# --- Verification: the core anti-hallucination guarantee --------------------


def test_verified_claim_with_exact_quote_is_returned():
    response = _fake_response([_fake_claim()])
    client = _FakeClient(response)

    result = extract_claims([TURN_1, TURN_2], client=client)

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.claim_text == "Q4 revenue was $48.4 billion."
    assert claim.category == "financial_performance"
    assert claim.source_turn_number == 1
    assert claim.source_quote == "Q4 total revenue was $48.4 billion"
    assert result.warnings == ()


def test_claim_with_unverifiable_quote_is_dropped_and_warned():
    bad_claim = _fake_claim(source_quote="revenue was up a lot, way more than expected")
    response = _fake_response([bad_claim])
    client = _FakeClient(response)

    result = extract_claims([TURN_1], client=client)

    assert result.claims == ()
    assert len(result.warnings) == 1
    assert "unverifiable source_quote" in result.warnings[0]


def test_claim_citing_nonexistent_turn_is_dropped_and_warned():
    bad_claim = _fake_claim(source_turn_number=99)
    response = _fake_response([bad_claim])
    client = _FakeClient(response)

    result = extract_claims([TURN_1], client=client)

    assert result.claims == ()
    assert len(result.warnings) == 1
    assert "nonexistent turn 99" in result.warnings[0]


def test_mix_of_valid_and_invalid_claims_keeps_only_valid_ones():
    good = _fake_claim(claim_text="good", source_quote="Q4 total revenue was $48.4 billion")
    bad = _fake_claim(claim_text="bad", source_quote="this text is not in the transcript")
    response = _fake_response([good, bad])
    client = _FakeClient(response)

    result = extract_claims([TURN_1], client=client)

    assert len(result.claims) == 1
    assert result.claims[0].claim_text == "good"
    assert len(result.warnings) == 1


# --- Refusal / truncation handling ------------------------------------------


def test_none_parsed_output_raises_claim_extraction_error():
    response = _fake_response([], stop_reason="refusal_no_output")
    client = _FakeClient(response)

    with pytest.raises(ClaimExtractionError, match="refusal"):
        extract_claims([TURN_1], client=client)


class _TinyModel(BaseModel):
    claims: list


class _TruncatedJSONMessages:
    """Regression test double for a real failure mode hit during live testing:
    the SDK's client.messages.parse() raises pydantic.ValidationError directly
    (never returning a response object) when max_tokens truncates the output
    mid-JSON — see KNOWN_ISSUES.md.
    """

    def parse(self, **kwargs):
        _TinyModel.model_validate_json('{"claims": [{"claim_text": "trunc')


def test_truncated_json_response_raises_claim_extraction_error_not_raw_pydantic_error():
    client = SimpleNamespace(messages=_TruncatedJSONMessages())

    with pytest.raises(ClaimExtractionError, match="truncated") as exc_info:
        extract_claims([TURN_1], client=client)

    # The raw pydantic error is chained, not swallowed — useful for debugging,
    # but callers should catch ClaimExtractionError, not ValidationError.
    assert isinstance(exc_info.value.__cause__, ValidationError)


# --- Empty input short-circuits without an API call -------------------------


def test_empty_turns_returns_empty_result_without_calling_api():
    client = _NeverCalledClient()

    result = extract_claims([], client=client)

    assert result.claims == ()
    assert result.warnings == ()
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0
    assert result.usage.stage == STAGE


# --- Usage tagging (Phase 2 cost-instrumentation prep) ----------------------


def test_usage_is_tagged_with_extraction_stage_and_model():
    response = _fake_response([], input_tokens=123, output_tokens=45)
    client = _FakeClient(response)

    result = extract_claims([TURN_1], client=client)

    assert result.usage.stage == "extraction"
    assert result.usage.model == DEFAULT_MODEL
    assert result.usage.input_tokens == 123
    assert result.usage.output_tokens == 45


def test_usage_logger_hook_is_invoked_with_the_same_usage():
    response = _fake_response([])
    client = _FakeClient(response)
    logged = []

    result = extract_claims([TURN_1], client=client, usage_logger=logged.append)

    assert logged == [result.usage]


def test_custom_model_is_passed_through_and_recorded():
    response = _fake_response([])
    client = _FakeClient(response)

    result = extract_claims([TURN_1], client=client, model="claude-sonnet-5")

    assert client.messages.last_call_kwargs["model"] == "claude-sonnet-5"
    assert result.usage.model == "claude-sonnet-5"


# --- Request shape: system prompt + user message ----------------------------


def test_request_includes_system_prompt_and_rendered_transcript():
    response = _fake_response([])
    client = _FakeClient(response)

    extract_claims([TURN_1, TURN_2], client=client)

    kwargs = client.messages.last_call_kwargs
    assert kwargs["max_tokens"] > 0
    system_blocks = kwargs["system"]
    assert isinstance(system_blocks, list)
    assert len(system_blocks) == 2
    # Second block (claim-categories.md) carries the cache_control marker.
    assert system_blocks[1]["cache_control"] == {"type": "ephemeral"}

    user_content = kwargs["messages"][0]["content"]
    assert "[Turn 1 | Prepared Remarks | Mark Zuckerberg, CEO]" in user_content
    assert "[Turn 2 | Q&A | Brian Nowak]" in user_content
    assert "$48.4 billion" in user_content


def test_load_system_prompt_strips_frontmatter_and_includes_categories():
    blocks = _load_system_prompt()
    combined = "\n".join(b["text"] for b in blocks)

    assert "---" not in combined.splitlines()[0]  # frontmatter delimiter gone
    assert "anti-hallucination" in combined.lower()
    for category in CATEGORY_VALUES:
        assert category in combined


def test_build_user_message_omits_title_when_none():
    message = _build_user_message([TURN_2])
    assert "[Turn 2 | Q&A | Brian Nowak]" in message
    assert "Brian Nowak," not in message

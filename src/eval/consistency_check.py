"""Consistency check — adaptive repeated-sampling for genuine judgment-call claims.

Per DECISIONS.md's model-tiering entry, `risk_factors` and `hedging_tone` claims
involve a real judgment call (materiality, hedging-vs-confidence framing) that
raw claim extraction does not — extraction should already be stable, so it's
not re-sampled here. Per DECISIONS.md's adaptive-sampling entry: run 2 samples
first; if they agree closely, stop and report as stable; only escalate to 5
total samples when they disagree. Per DECISIONS.md's variance-reporting entry:
report **median + range across the samples actually taken**, never a formal
confidence interval — this is explicitly not that.

See DECISIONS.md's 2026-08-12 entry ("Consistency-check judgment task") for
why `claude-opus-5`, a 1-5 integer scale, and a ≤1-point agreement threshold
were the specific numbers chosen here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Callable, Literal, Optional

import anthropic
from pydantic import BaseModel, Field, ValidationError

from src.extraction.claim_extractor import ExtractedClaim, TokenUsage

# Reserved for genuine judgment calls — see DECISIONS.md's model-tiering entry
# and this module's docstring. Deliberately NOT the cheap extraction-tier model.
JUDGMENT_MODEL = "claude-opus-5"

STAGE = "eval_consistency"

# First-two-samples agreement threshold (see DECISIONS.md) — a difference of
# this many points or fewer on the 1-5 scale counts as "agree closely" and
# sampling stops at N=2; anything wider escalates to N=5.
AGREEMENT_THRESHOLD = 1

FULL_SAMPLE_COUNT = 5
INITIAL_SAMPLE_COUNT = 2

JUDGMENT_CALL_CATEGORIES: frozenset[str] = frozenset({"risk_factors", "hedging_tone"})

_Dimension = Literal["materiality", "framing"]

_DIMENSION_BY_CATEGORY: dict[str, _Dimension] = {
    "risk_factors": "materiality",
    "hedging_tone": "framing",
}

_SYSTEM_PROMPTS: dict[_Dimension, str] = {
    "materiality": (
        "You are assessing how material a single risk-related claim from an earnings call is. "
        "Rate materiality on an integer scale from 1 to 5, where 1 means a minor, routine, "
        "boilerplate caveat with little real business impact, and 5 means a severe risk that "
        "could materially harm the company's business, results, or financial condition. Base "
        "your rating only on how the claim itself is framed — not on outside knowledge of the "
        "company. Respond with your integer score and a one-sentence rationale."
    ),
    "framing": (
        "You are assessing how hedged vs. confident a single claim from an earnings call is in "
        "its framing. Rate framing on an integer scale from 1 to 5, where 1 means strongly "
        "hedged/qualified language (heavy caveats, tentative phrasing) and 5 means strongly "
        "confident/unqualified language (firm, declarative statements). Respond with your "
        "integer score and a one-sentence rationale."
    ),
}


class _JudgmentScore(BaseModel):
    score: int = Field(ge=1, le=5)
    rationale: str


class ConsistencyCheckError(Exception):
    """Raised when a judgment-sampling call didn't produce parseable structured output.

    Covers a safety refusal and output truncation — see
    `src.extraction.claim_extractor.ClaimExtractionError`, whose failure modes
    (and this same wrap-the-SDK's-raw-ValidationError fix) this mirrors.
    """


@dataclass(frozen=True)
class ConsistencyResult:
    """Consistency-check verdict for one judgment-call claim."""

    claim_text: str
    category: str
    dimension: str  # "materiality" or "framing"
    samples: tuple[int, ...]  # every score collected, in call order (2 or 5 of them)
    median: float
    range_low: int
    range_high: int
    stable: bool  # True: the first 2 samples agreed closely, no escalation needed
    escalated: bool  # True: samples disagreed, escalated to 5 total


def _build_user_message(claim: ExtractedClaim) -> str:
    return f'Claim: "{claim.claim_text}"\n\nSource quote: "{claim.source_quote}"'


def _sample_judgment(
    claim: ExtractedClaim, dimension: _Dimension, client: anthropic.Anthropic, model: str
) -> tuple[int, TokenUsage]:
    """Make one judgment-sampling call and return (score, usage)."""
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=512,
            # Thinking is on by default on claude-opus-5, and max_tokens caps
            # thinking + answer text *combined* — a small max_tokens (this is
            # a one-sentence-rationale task, not one that needs deep
            # reasoning) let the model spend the whole budget thinking and
            # return zero text, which fails JSON parsing below with an EOF
            # error on an *empty* string (found live-testing this module —
            # see KNOWN_ISSUES.md). Disabling thinking is accepted at the
            # default effort ("high" or below) and is the right fix here:
            # this task doesn't need it, and it guarantees max_tokens goes
            # entirely to the answer.
            thinking={"type": "disabled"},
            system=_SYSTEM_PROMPTS[dimension],
            messages=[{"role": "user", "content": _build_user_message(claim)}],
            output_format=_JudgmentScore,
        )
    except ValidationError as exc:
        # The SDK raises this directly (no response object) when output is
        # truncated by max_tokens before the JSON closes — see
        # ClaimExtractionError's docstring and KNOWN_ISSUES.md for the same
        # failure mode found live-testing extraction. 512 tokens should be
        # generous for a 1-5 score + one sentence, but fail loud, not silent.
        raise ConsistencyCheckError(
            f"Judgment-sampling output did not parse as valid JSON for claim "
            f"{claim.claim_text[:60]!r}... — likely truncated by max_tokens."
        ) from exc

    usage = TokenUsage(
        stage=STAGE,
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0)
        or 0,
        cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    )

    parsed = response.parsed_output
    if parsed is None:
        raise ConsistencyCheckError(
            f"Judgment-sampling call did not produce parseable output (stop_reason="
            f"{response.stop_reason!r}) for claim {claim.claim_text[:60]!r}..."
        )

    return parsed.score, usage


def assess_consistency(
    claim: ExtractedClaim,
    client: Optional[anthropic.Anthropic] = None,
    model: str = JUDGMENT_MODEL,
    usage_logger: Optional[Callable[[TokenUsage], None]] = None,
) -> tuple[ConsistencyResult, tuple[TokenUsage, ...]]:
    """Run adaptive N=2->5 consistency sampling on one judgment-call claim.

    Args:
        claim: An ExtractedClaim whose category is in JUDGMENT_CALL_CATEGORIES.
        client: An `anthropic.Anthropic` client. Defaults to `Anthropic()`.
        model: Model ID to sample with. Defaults to JUDGMENT_MODEL (the
            strongest tier — see DECISIONS.md).
        usage_logger: Optional callback invoked once per sample with that
            call's `TokenUsage`, tagged `stage="eval_consistency"`.

    Returns:
        (result, usages) — the ConsistencyResult and every TokenUsage produced.

    Raises:
        ValueError: if claim.category isn't a judgment-call category.
        ConsistencyCheckError: if a sampling call didn't produce parseable output.
    """
    if claim.category not in JUDGMENT_CALL_CATEGORIES:
        raise ValueError(
            f"assess_consistency called on a non-judgment-call category "
            f"{claim.category!r}; expected one of {sorted(JUDGMENT_CALL_CATEGORIES)}"
        )

    dimension = _DIMENSION_BY_CATEGORY[claim.category]
    client = client or anthropic.Anthropic()

    scores: list[int] = []
    usages: list[TokenUsage] = []

    def _sample() -> None:
        score, usage = _sample_judgment(claim, dimension, client, model)
        scores.append(score)
        usages.append(usage)
        if usage_logger:
            usage_logger(usage)

    for _ in range(INITIAL_SAMPLE_COUNT):
        _sample()

    stable = (max(scores) - min(scores)) <= AGREEMENT_THRESHOLD
    escalated = not stable

    if escalated:
        for _ in range(FULL_SAMPLE_COUNT - INITIAL_SAMPLE_COUNT):
            _sample()

    result = ConsistencyResult(
        claim_text=claim.claim_text,
        category=claim.category,
        dimension=dimension,
        samples=tuple(scores),
        median=statistics.median(scores),
        range_low=min(scores),
        range_high=max(scores),
        stable=stable,
        escalated=escalated,
    )
    return result, tuple(usages)

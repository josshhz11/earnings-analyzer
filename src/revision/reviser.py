"""Targeted revision — corrects only the claims the eval harness flagged as failing.

Per DECISIONS.md's targeted-revision entry: when the eval harness flags specific
claims, only those claims get sent back for correction — the whole draft claims
list is never regenerated from scratch. Two failure kinds trigger revision:

1. **Unfaithful quote** — `faithfulness_check.py` couldn't verify the claim's
   `source_quote` against its cited turn.
2. **High-variance judgment call** — `consistency_check.py` escalated to the
   full 5 samples *and* the final spread across those 5 samples stayed wide
   (see HIGH_VARIANCE_RANGE_THRESHOLD) — a genuinely unstable judgment, not
   just a claim that needed a couple of extra samples to settle.

Uses the strongest available model tier in this repo's catalog (revision means
reasoning about *why* something failed, not bounded extraction — see
DECISIONS.md's model-tiering entry), tagged `stage="revision"` for Phase 2's
per-stage cost logging. Re-runs the faithfulness check on the revised claims
list before returning, so the caller gets proof the fix actually worked, not
just that a new answer was produced.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Literal, Optional, Union

import anthropic
from pydantic import BaseModel, Field, ValidationError

from src.eval.consistency_check import JUDGMENT_CALL_CATEGORIES
from src.eval.eval_harness import EvalReport
from src.eval.faithfulness_check import FaithfulnessReport, check_faithfulness
from src.extraction.claim_extractor import Category, ExtractedClaim, TokenUsage
from src.ingestion.segmentation import Turn

# Strongest tier in this repo's model catalog — same choice and reasoning as
# consistency_check.JUDGMENT_MODEL (see DECISIONS.md's model-tiering entry
# and its 2026-08-12 reconsideration-and-confirmation entry). Each stage owns
# its own constant rather than importing the other's, even though the value
# is currently the same, so the two concerns (judgment sampling vs. revision)
# stay independently changeable.
REVISION_MODEL = "claude-opus-5"

STAGE = "revision"

# An escalated (5-sample) consistency result only counts as "worth
# reconsidering" if the final spread across all 5 samples is still this wide
# or wider — an escalation that converged tightly by sample 5 isn't a real
# instability, just a case that needed a couple of extra samples to settle.
HIGH_VARIANCE_RANGE_THRESHOLD = 2

_RevisionReason = Literal["unfaithful_quote", "high_variance_judgment"]

_SYSTEM_PROMPT = (
    "You are revising a single previously-extracted earnings-call claim that failed "
    "verification. The same anti-hallucination rule that applied during extraction still "
    "applies: never invent or approximate a source_quote — it must be an exact, verbatim "
    "substring of the transcript turn text you are given. If the turn's text does not actually "
    "support a checkable claim like this, discard it rather than forcing a correction that isn't "
    "really grounded. Respond with either a corrected claim or a decision to discard, plus a "
    "brief one-sentence reasoning for your decision."
)


class _CorrectedClaim(BaseModel):
    action: Literal["corrected"]
    claim_text: str
    category: Category
    source_quote: str
    confidence_flag: bool
    reasoning: str


class _DiscardedClaim(BaseModel):
    action: Literal["discard"]
    reasoning: str


class _RevisionResponseSchema(BaseModel):
    result: Union[_CorrectedClaim, _DiscardedClaim] = Field(discriminator="action")


class RevisionError(Exception):
    """Raised when a revision call didn't produce parseable structured output.

    Same failure modes (and the same wrap-the-SDK's-raw-ValidationError fix)
    as ClaimExtractionError and ConsistencyCheckError.
    """


@dataclass(frozen=True)
class RevisionOutcome:
    """What happened to one flagged claim during revision."""

    original_claim: ExtractedClaim
    reasons: tuple[_RevisionReason, ...]
    action: Literal["corrected", "discard"]
    revised_claim: Optional[ExtractedClaim]  # None when action == "discard"
    model_reasoning: str


@dataclass(frozen=True)
class RevisionResult:
    revised_claims: tuple[ExtractedClaim, ...]  # full list: untouched + corrected, discards removed
    outcomes: tuple[RevisionOutcome, ...]  # one per claim that was sent for revision
    post_revision_faithfulness: FaithfulnessReport  # proof the fix actually worked
    usage: tuple[TokenUsage, ...]


def _claims_needing_revision(
    claims: list[ExtractedClaim],
    eval_report: EvalReport,
    high_variance_range_threshold: int,
) -> list[tuple[ExtractedClaim, list[_RevisionReason], list[str]]]:
    """Identify flagged claims and why, deduplicating a claim flagged by both checks.

    Relies on `eval_report` having been produced by `run_eval(claims, turns, ...)`
    against this exact `claims` list — `check_faithfulness` and `run_eval`'s
    judgment-claim filtering are both order-preserving over `claims`, which is
    what lets this function zip the report's results back onto the claims
    that produced them without the report itself carrying claim references.
    """
    if len(claims) != len(eval_report.faithfulness.results):
        raise ValueError(
            "eval_report.faithfulness doesn't match claims — was eval_report produced by "
            "run_eval(claims, turns, ...) with this exact claims list?"
        )

    reasons_by_claim: dict[ExtractedClaim, list[_RevisionReason]] = defaultdict(list)
    contexts_by_claim: dict[ExtractedClaim, list[str]] = defaultdict(list)

    for claim, result in zip(claims, eval_report.faithfulness.results):
        if not result.passed:
            reasons_by_claim[claim].append("unfaithful_quote")
            contexts_by_claim[claim].append(f"Faithfulness check failed: {result.reason}")

    judgment_claims = [c for c in claims if c.category in JUDGMENT_CALL_CATEGORIES]
    if len(judgment_claims) != len(eval_report.consistency):
        raise ValueError(
            "eval_report.consistency doesn't match claims — was eval_report produced by "
            "run_eval(claims, turns, ...) with this exact claims list?"
        )

    for claim, result in zip(judgment_claims, eval_report.consistency):
        spread = result.range_high - result.range_low
        if result.escalated and spread >= high_variance_range_threshold:
            reasons_by_claim[claim].append("high_variance_judgment")
            contexts_by_claim[claim].append(
                f"Consistency check disagreed on {result.dimension}: samples={result.samples}, "
                f"median={result.median}, range=({result.range_low}, {result.range_high})."
            )

    return [(claim, reasons_by_claim[claim], contexts_by_claim[claim]) for claim in reasons_by_claim]


def _build_revision_prompt(
    claim: ExtractedClaim, turn: Turn, contexts: list[str]
) -> str:
    context_block = "\n".join(f"- {c}" for c in contexts)
    return (
        "You previously extracted this claim from an earnings call transcript:\n\n"
        f'claim_text: "{claim.claim_text}"\n'
        f"category: {claim.category}\n"
        f"source_turn_number: {claim.source_turn_number}\n"
        f'source_quote: "{claim.source_quote}"\n\n'
        f"This claim was flagged by the eval harness:\n{context_block}\n\n"
        f"Here is the actual full text of turn {claim.source_turn_number}, the turn this claim "
        f'cites:\n"{turn.text}"\n\n'
        "Reconsider this claim. If it can be corrected — a claim_text and category genuinely "
        "supported by an exact, verbatim substring of the turn text above — provide the "
        "corrected claim. If no claim like this is actually supported by this turn's text, "
        "indicate it should be discarded rather than inventing a quote to fit."
    )


def _sample_revision(
    claim: ExtractedClaim,
    turn: Turn,
    contexts: list[str],
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
) -> tuple[Union[_CorrectedClaim, _DiscardedClaim], TokenUsage]:
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            # Thinking is deliberately left on (adaptive, the default) here —
            # unlike consistency_check.py's trivial 1-5 scoring task, revision
            # genuinely benefits from reasoning about why the claim failed
            # (see module docstring). max_tokens is kept generous since
            # max_tokens caps thinking + answer text combined on this model
            # (see KNOWN_ISSUES.md for the consistency-check bug this same
            # interaction caused when max_tokens was too small).
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_revision_prompt(claim, turn, contexts)}],
            output_format=_RevisionResponseSchema,
        )
    except ValidationError as exc:
        raise RevisionError(
            f"Revision output did not parse as valid JSON (max_tokens={max_tokens}) for claim "
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
        raise RevisionError(
            f"Revision call did not produce parseable output (stop_reason="
            f"{response.stop_reason!r}) for claim {claim.claim_text[:60]!r}..."
        )

    return parsed.result, usage


def revise_claims(
    claims: list[ExtractedClaim],
    eval_report: EvalReport,
    turns: list[Turn],
    client: Optional[anthropic.Anthropic] = None,
    model: str = REVISION_MODEL,
    max_tokens: int = 4096,
    high_variance_range_threshold: int = HIGH_VARIANCE_RANGE_THRESHOLD,
    usage_logger: Optional[Callable[[TokenUsage], None]] = None,
) -> RevisionResult:
    """Send only eval-flagged claims back for a targeted correction, then re-verify.

    Args:
        claims: The draft claims list eval_report was computed from.
        eval_report: An EvalReport from `src.eval.eval_harness.run_eval(claims, turns, ...)`
            — must have been produced from this exact `claims` list (order-sensitive,
            see `_claims_needing_revision`).
        turns: The segmented transcript the claims were extracted from.
        client: An `anthropic.Anthropic` client. Defaults to `Anthropic()`.
        model: Model ID for revision calls. Defaults to REVISION_MODEL (the
            strongest tier — see DECISIONS.md).
        max_tokens: Output token cap per revision call (thinking + answer combined).
        high_variance_range_threshold: Minimum final sample spread (on an
            escalated consistency result) to count as worth revising.
        usage_logger: Optional callback invoked once per revision call with
            that call's `TokenUsage`, tagged `stage="revision"`.

    Returns:
        A RevisionResult: the full revised claims list (corrections applied,
        discards removed, everything else untouched), per-claim outcomes for
        building a before/after diff, a fresh FaithfulnessReport over the
        revised list (proof the fix worked, not just that a new answer
        arrived), and every TokenUsage produced.
    """
    to_revise = _claims_needing_revision(claims, eval_report, high_variance_range_threshold)

    outcomes: list[RevisionOutcome] = []
    usages: list[TokenUsage] = []

    if to_revise:
        client = client or anthropic.Anthropic()
        turns_by_number = {t.turn_number: t for t in turns}

        for claim, reasons, contexts in to_revise:
            turn = turns_by_number.get(claim.source_turn_number)
            if turn is None:
                # Nothing to revise against — the cited turn doesn't exist,
                # so there's no transcript text to ground a correction in.
                # Discard automatically without spending an API call on it.
                outcomes.append(
                    RevisionOutcome(
                        original_claim=claim,
                        reasons=tuple(reasons),
                        action="discard",
                        revised_claim=None,
                        model_reasoning=(
                            f"source_turn_number {claim.source_turn_number} does not exist in "
                            "the transcript — discarded without a revision call."
                        ),
                    )
                )
                continue

            result, usage = _sample_revision(claim, turn, contexts, client, model, max_tokens)
            usages.append(usage)
            if usage_logger:
                usage_logger(usage)

            if isinstance(result, _DiscardedClaim):
                outcomes.append(
                    RevisionOutcome(
                        original_claim=claim,
                        reasons=tuple(reasons),
                        action="discard",
                        revised_claim=None,
                        model_reasoning=result.reasoning,
                    )
                )
            else:
                revised_claim = ExtractedClaim(
                    claim_text=result.claim_text,
                    category=result.category,
                    source_turn_number=claim.source_turn_number,  # revision doesn't re-attribute turns
                    source_quote=result.source_quote,
                    confidence_flag=result.confidence_flag,
                )
                outcomes.append(
                    RevisionOutcome(
                        original_claim=claim,
                        reasons=tuple(reasons),
                        action="corrected",
                        revised_claim=revised_claim,
                        model_reasoning=result.reasoning,
                    )
                )

    outcomes_by_original = {o.original_claim: o for o in outcomes}
    revised_claims: list[ExtractedClaim] = []
    for claim in claims:
        outcome = outcomes_by_original.get(claim)
        if outcome is None:
            revised_claims.append(claim)
        elif outcome.revised_claim is not None:
            revised_claims.append(outcome.revised_claim)
        # else: discarded, omit from the revised list

    post_revision_faithfulness = check_faithfulness(revised_claims, turns)

    return RevisionResult(
        revised_claims=tuple(revised_claims),
        outcomes=tuple(outcomes),
        post_revision_faithfulness=post_revision_faithfulness,
        usage=tuple(usages),
    )

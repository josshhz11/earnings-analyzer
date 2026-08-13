"""Claim extraction — the first LLM-calling stage of the pipeline.

Calls Claude once against a segmented transcript and returns structured,
source-cited claims, using the `earnings-call-analysis` skill
(`skills/earnings-call-analysis/SKILL.md` + `reference/claim-categories.md`)
as the system prompt.

Per DECISIONS.md's model-tiering entry, this is a bounded extraction task —
not a judgment call — so it uses the cheapest/fastest current model
(`DEFAULT_MODEL`), not the strongest one.

Every claim is verified programmatically against the transcript before being
returned. Per CLAUDE.md's anti-hallucination contract ("no un-sourced claims,
ever"), this module never trusts the model's own claim of faithfulness — a
claim whose `source_quote` isn't a verbatim substring of its cited turn is
dropped and logged as a warning, not silently kept. This is a cheap first
line of defense at extraction time; the full faithfulness/consistency eval
harness is a separate future pipeline stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

import anthropic
from pydantic import BaseModel, ValidationError

from src.ingestion.segmentation import Turn

# Cheapest/fastest current model — this is a bounded extraction task, not a
# judgment call, per DECISIONS.md's model-tiering entry. Don't "upgrade" this
# without updating that entry and its stated reasoning.
DEFAULT_MODEL = "claude-haiku-4-5"

# Tag applied to every TokenUsage this module produces — see ROADMAP.md
# Phase 2 (per-stage token usage logging).
STAGE = "extraction"

_SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "earnings-call-analysis"
SKILL_PATH = _SKILL_DIR / "SKILL.md"
CLAIM_CATEGORIES_PATH = _SKILL_DIR / "reference" / "claim-categories.md"

# Must match the category slugs used in reference/claim-categories.md exactly.
CATEGORY_VALUES: tuple[str, ...] = (
    "financial_performance",
    "guidance",
    "risk_factors",
    "segment_performance",
    "non_gaap_vs_gaap",
    "hedging_tone",
)

# Public (not underscore-prefixed) — src/eval and src/revision both reuse this
# type when building their own structured-output schemas over claim categories.
Category = Literal[
    "financial_performance",
    "guidance",
    "risk_factors",
    "segment_performance",
    "non_gaap_vs_gaap",
    "hedging_tone",
]


class _ClaimSchema(BaseModel):
    """Structured-output schema for one claim — see `output_config.format`."""

    claim_text: str
    category: Category
    source_turn_number: int
    source_quote: str
    confidence_flag: bool


class _ExtractionOutputSchema(BaseModel):
    """Top-level structured-output schema (must be an object, not a bare array)."""

    claims: list[_ClaimSchema]


class ClaimExtractionError(Exception):
    """Raised when the model call fails to produce parseable structured output.

    Covers a safety refusal (`stop_reason == "refusal"`) and truncation
    (`stop_reason == "max_tokens"`, incomplete JSON) — both leave
    `response.parsed_output` as `None`.
    """


@dataclass(frozen=True)
class ExtractedClaim:
    """One verified claim: its source_quote is confirmed present in the cited turn."""

    claim_text: str
    category: str
    source_turn_number: int
    source_quote: str
    confidence_flag: bool


@dataclass(frozen=True)
class TokenUsage:
    """Per-call token usage, tagged by pipeline stage.

    Every LLM call in the pipeline should produce one of these — see
    OVERALL_PROJECT.md's cost-optimization goal and ROADMAP.md Phase 2
    (per-stage token usage logging, tagged and queryable). `usage_logger` on
    `extract_claims` is the hook Phase 2 wires real persistence into; until
    then, callers just read `ExtractionResult.usage`.
    """

    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True)
class ExtractionResult:
    claims: tuple[ExtractedClaim, ...]
    warnings: tuple[str, ...]
    usage: TokenUsage


def _load_system_prompt() -> list[dict]:
    """Build the system prompt from SKILL.md + claim-categories.md.

    Returned as a content-block list (not a bare string) with a
    `cache_control` marker on the reference-material block, so Phase 2's
    prompt-caching work (ROADMAP.md) can start relying on it without
    refactoring this call site. Below the model's cache-write token minimum
    this is a harmless no-op — no error, it just doesn't cache yet.
    """
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    # Strip the YAML frontmatter (--- ... ---) — only the instructions body
    # goes to the model; name/description are for human/tool discovery.
    if skill_text.startswith("---"):
        end = skill_text.find("---", 3)
        if end != -1:
            skill_text = skill_text[end + 3 :].strip()

    categories_text = CLAIM_CATEGORIES_PATH.read_text(encoding="utf-8")

    return [
        {"type": "text", "text": skill_text},
        {
            "type": "text",
            "text": categories_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _build_user_message(turns: list[Turn]) -> str:
    """Render segmented turns as the transcript the model extracts from."""
    lines = []
    for turn in turns:
        title = f", {turn.speaker_title}" if turn.speaker_title else ""
        lines.append(
            f"[Turn {turn.turn_number} | {turn.section} | {turn.speaker_name}{title}]\n{turn.text}"
        )
    transcript = "\n\n".join(lines)
    return (
        "Extract claims from the following segmented earnings call transcript. "
        "Each turn is labeled with its turn number, section, and speaker.\n\n"
        f"{transcript}"
    )


def _verify_claims(
    claims: list[_ClaimSchema], turns_by_number: dict[int, Turn]
) -> tuple[tuple[ExtractedClaim, ...], tuple[str, ...]]:
    """Programmatically verify every claim's source_quote against the transcript.

    A claim whose cited turn doesn't exist, or whose source_quote isn't a
    verbatim substring of that turn's text, is dropped — never returned
    un-sourced. This does not replace the eval harness's faithfulness check
    (a future stage); it's a cheap first line of defense at extraction time.
    """
    verified: list[ExtractedClaim] = []
    warnings: list[str] = []

    for claim in claims:
        turn = turns_by_number.get(claim.source_turn_number)
        if turn is None:
            warnings.append(
                f"Dropped claim citing nonexistent turn {claim.source_turn_number}: "
                f"{claim.claim_text[:60]!r}..."
            )
            continue
        if claim.source_quote not in turn.text:
            warnings.append(
                "Dropped claim with unverifiable source_quote (not found verbatim in "
                f"turn {claim.source_turn_number}): {claim.claim_text[:60]!r}..."
            )
            continue
        verified.append(
            ExtractedClaim(
                claim_text=claim.claim_text,
                category=claim.category,
                source_turn_number=claim.source_turn_number,
                source_quote=claim.source_quote,
                confidence_flag=claim.confidence_flag,
            )
        )

    return tuple(verified), tuple(warnings)


def extract_claims(
    turns: list[Turn],
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    usage_logger: Optional[Callable[[TokenUsage], None]] = None,
) -> ExtractionResult:
    """Extract categorized, source-cited claims from a segmented transcript.

    Calls `model` once against the full transcript using structured outputs
    (guarantees valid, schema-conformant JSON — see
    `python/claude-api/tool-use.md` § Structured Outputs), then
    programmatically verifies every claim's `source_quote` before returning
    it (see module docstring).

    Args:
        turns: Segmented transcript turns (from `src.ingestion.segmentation`).
        client: An `anthropic.Anthropic` client. Defaults to `Anthropic()`,
            which resolves credentials from the environment (`ANTHROPIC_API_KEY`,
            `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile).
        model: Model ID to call. Defaults to the cheapest/fastest current
            tier — see DEFAULT_MODEL and DECISIONS.md.
        max_tokens: Output token cap for the extraction response. Default is
            8192, not the SDK's typical 4096 default — a JSON claims list for
            even a handful of turns can exceed 4096 tokens (observed directly:
            6 turns of a real transcript truncated mid-JSON at the 4096
            default, see KNOWN_ISSUES.md). Stay well under ~16000 here, since
            this call is non-streaming and larger values risk an SDK HTTP
            timeout.
        usage_logger: Optional callback invoked with the call's `TokenUsage`,
            tagged `stage="extraction"` — the hook Phase 2's cost
            instrumentation wires real logging into.

    Returns:
        An ExtractionResult with verified claims, any drop/verification
        warnings, and the call's token usage.

    Raises:
        ClaimExtractionError: if the model call didn't produce parseable
            structured output — a safety refusal, or output truncated by
            `max_tokens` before the JSON closed (raise `max_tokens` or pass
            fewer turns per call if this happens repeatedly).
    """
    if not turns:
        usage = TokenUsage(stage=STAGE, model=model, input_tokens=0, output_tokens=0)
        return ExtractionResult(claims=(), warnings=(), usage=usage)

    client = client or anthropic.Anthropic()

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=_load_system_prompt(),
            messages=[{"role": "user", "content": _build_user_message(turns)}],
            output_format=_ExtractionOutputSchema,
        )
    except ValidationError as exc:
        # The SDK raises this directly (before returning a response object)
        # when the response text isn't valid JSON for the schema — in
        # practice this means the output was cut off mid-JSON by max_tokens,
        # not a schema mismatch (structured outputs guarantees schema
        # conformance for *complete* output). There's no `response` here to
        # inspect `stop_reason` on, so state the likely cause directly.
        raise ClaimExtractionError(
            f"Model output did not parse as valid JSON (max_tokens={max_tokens}). "
            "This almost always means the response was truncated before the JSON "
            "closed — raise max_tokens or send fewer turns per call."
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
    if usage_logger:
        usage_logger(usage)

    parsed = response.parsed_output
    if parsed is None:
        raise ClaimExtractionError(
            f"Model call did not produce parseable output (stop_reason="
            f"{response.stop_reason!r}). This is usually a safety refusal or "
            "output truncation — inspect the raw response before retrying."
        )

    turns_by_number = {t.turn_number: t for t in turns}
    claims, warnings = _verify_claims(parsed.claims, turns_by_number)

    return ExtractionResult(claims=claims, warnings=warnings, usage=usage)

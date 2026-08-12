"""Eval harness — ties faithfulness, coverage, and consistency checks together.

Per OVERALL_PROJECT.md's architecture section: faithfulness and coverage are
fully programmatic (no LLM calls); consistency is the one check that samples
an LLM, and only for the small subset of claims in judgment-call categories
(see consistency_check.py). Running `run_eval` on a draft claims list produces
one structured `EvalReport` covering all three.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import anthropic

from src.eval.consistency_check import (
    JUDGMENT_CALL_CATEGORIES,
    JUDGMENT_MODEL,
    ConsistencyResult,
    assess_consistency,
)
from src.eval.coverage_check import CoverageReport, check_coverage
from src.eval.faithfulness_check import FaithfulnessReport, check_faithfulness
from src.extraction.claim_extractor import ExtractedClaim, TokenUsage
from src.ingestion.segmentation import Turn


@dataclass(frozen=True)
class EvalReport:
    faithfulness: FaithfulnessReport
    coverage: CoverageReport
    consistency: tuple[ConsistencyResult, ...]
    usage: tuple[TokenUsage, ...]  # every consistency-check API call made, if any


def run_eval(
    claims: list[ExtractedClaim],
    turns: list[Turn],
    client: Optional[anthropic.Anthropic] = None,
    model: str = JUDGMENT_MODEL,
    usage_logger: Optional[Callable[[TokenUsage], None]] = None,
) -> EvalReport:
    """Run faithfulness, coverage, and consistency checks against a draft claims list.

    Faithfulness and coverage are deterministic and always run. Consistency
    only runs — and only makes API calls — for claims whose category is in
    JUDGMENT_CALL_CATEGORIES; if none are present, no client is constructed
    and no call is made, so this function works credential-free on a claims
    list with no judgment-call claims.

    Args:
        claims: Claims to evaluate (e.g. `ExtractionResult.claims` from
            `src.extraction.claim_extractor.extract_claims`).
        turns: The segmented transcript the claims were extracted from.
        client: An `anthropic.Anthropic` client for consistency sampling.
            Only constructed/used if a judgment-call claim is present.
        model: Model ID for consistency sampling. Defaults to JUDGMENT_MODEL.
        usage_logger: Optional callback invoked once per consistency-check
            API call with that call's `TokenUsage`.

    Returns:
        An EvalReport bundling all three checks' results.
    """
    faithfulness = check_faithfulness(claims, turns)
    coverage = check_coverage(claims, turns)

    judgment_claims = [c for c in claims if c.category in JUDGMENT_CALL_CATEGORIES]

    consistency: list[ConsistencyResult] = []
    usage: list[TokenUsage] = []

    if judgment_claims:
        client = client or anthropic.Anthropic()
        for claim in judgment_claims:
            result, usages = assess_consistency(
                claim, client=client, model=model, usage_logger=usage_logger
            )
            consistency.append(result)
            usage.extend(usages)

    return EvalReport(
        faithfulness=faithfulness,
        coverage=coverage,
        consistency=tuple(consistency),
        usage=tuple(usage),
    )

# OVERALL_PROJECT.md

Stable reference for what this project is. This file should rarely change — if you find
yourself editing it often, the change probably belongs in STATE.md or ROADMAP.md instead.

## What this is

Earnings Analyzer: an agentic pipeline that ingests an earnings call transcript, extracts
categorized and source-cited claims (financial performance, forward guidance, risk factors,
hedging/tone), verifies those claims against the source document via an eval harness, revises
anything that fails verification, and produces a structured report.

## Why it exists / origin

This project replaced an earlier "AI Resume Reviewer" concept. The architecture — agentic
extraction, an eval harness with faithfulness + consistency checks, a generate-critique-revise
loop — was designed first for the resume tool, then ported here deliberately, because:

1. **Financial claims are more rigorously checkable than resume-quality judgments.** A resume
   claim like "this bullet lacks quantification" is subjective. A financial claim like "revenue
   grew 12% YoY" is either backed by the source numbers or it isn't — faithfulness-checking
   becomes closer to exact matching, which is a stronger, more defensible eval design.
2. **"AI resume reviewer" is an oversaturated demo project category.** This isn't.
3. **This project is relevant to both halves of the target job search** — AI/agentic engineering
   roles (the eval-harness, self-critique-loop story) *and* quant/finance roles (the domain
   itself, and financial-document literacy), where the resume version only served the first half.

## Target audience for this as a portfolio piece

AI-agentic engineering roles (evidence: real eval harness, measured hallucination/consistency
rate, not just "I called an LLM") and quantitative/finance roles (evidence: financial-document
literacy, correctly modeling what claims in a 10-Q/earnings call actually mean and how they're
scrutinized).

## v1 scope (current)

- **Input:** earnings call transcript, PDF upload only. No URL ingestion, no speech-to-text yet.
- **Single document.** No cross-document comparison (no "this quarter vs last quarter",
  no analyst-consensus matching).
- **No auth, no persistence between runs beyond local caching.** This is a pipeline you run,
  not a multi-user app — deliberately, to avoid the mistake made on an earlier project (StudyRAG)
  of building persistence/auth/multi-tenancy before the core pipeline logic was proven.

## Explicit non-goals for v1 (don't scope-creep these in)

- SEC filings (10-Q, 10-K) — planned for v2, see ROADMAP.md, deliberately deferred because
  transcripts have no table-extraction requirement and let the core pipeline get proven first.
- Cross-document / cross-period comparison.
- A web UI / user accounts.
- Speech-to-text from live calls.
- Any claim about whether a company is a "good investment" — this tool verifies and reports
  claims, it does not generate investment recommendations.

## Architecture (5 stages, each a separate module — see CLAUDE.md for code-organization rules)

1. **Ingestion** — PDF → structured text with speaker-turn segmentation (Prepared Remarks vs.
   Q&A, speaker name/title tagged per turn). Deterministic, no LLM.
2. **Extraction** — an LLM skill (`skills/earnings-call-analysis/SKILL.md`) extracts atomic
   claims: text, category tag, source turn number, direct quote for verification.
3. **Eval harness** — faithfulness check (claim's cited quote actually appears in source,
   programmatic), consistency check (repeated sampling on judgment-call categories, adaptive
   N=2→5, median + range reported), coverage check (all expected sections processed).
4. **Revision** — targeted correction of only the claims/categories the eval harness flagged,
   not a full regeneration.
5. **Report** — categorized claims with citations, eval appendix (faithfulness rate, variance
   ranges), Markdown/PDF export.

## Claim categories (the rubric-equivalent for this project)

1. Financial performance (revenue, margins, EPS, cash flow — as *stated on the call*, no table
   cross-check in v1 since transcripts have no tables; that verification arrives with v2's 10-Q
   table extraction)
2. Guidance / forward-looking statements
3. Risk factors as discussed
4. Segment/business-line performance
5. Hedging/tone language (qualified vs. unqualified statements — detected via phrase lexicon,
   see `skills/earnings-call-analysis/reference/hedging-lexicon.md`)
6. Non-GAAP vs. GAAP references (flagged where the call distinguishes adjusted vs. reported
   figures)

## Cost-optimization as an explicit learning goal

This project is also being used deliberately to learn LLM cost optimization in general
(stated goal, not just an implementation detail). Every pipeline stage logs token usage,
tagged by stage, so cost can be broken down and iterated on. See DECISIONS.md for the specific
techniques applied (model tiering, prompt caching, adaptive sampling, targeted revision,
Batch API for dev-time runs) and ROADMAP.md for when cost instrumentation gets built.

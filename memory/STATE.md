# STATE.md

**Last updated:** 2026-08-13
**Current phase:** Phase 1 — core pipeline. Ingestion, hedging detection, claim extraction, the
eval harness, and the targeted revision loop are all built and working. Report generation is
next — that's the last piece of the core Phase 1 loop.

This file always reflects *current reality only*. Don't leave stale entries — if something
described here stops being true, overwrite it, don't append. History belongs in DECISIONS.md,
not here.

## What actually works right now

**`src/ingestion/` — deterministic PDF loading + speaker-turn segmentation. No LLM calls.**

- `pdf_loader.load_pdf_text(path)` — extracts text via pymupdf, page by page. Raises
  `PDFTextExtractionError` for missing/corrupt/zero-page/near-empty-text-layer PDFs (the
  scanned-transcript case). Returns a `LoadedDocument(source_path, page_count, text)`.
- `segmentation.segment_transcript(text)` — parses raw text into `Turn(turn_number,
  speaker_name, speaker_title, section, text)` objects. Handles two real-world cue styles
  (standalone "Name, Title" headers and inline "Name: text" cues, including dense transcripts
  with no blank-line separation between turns). Locates the Prepared Remarks -> Q&A boundary via
  heading/keyword/fallback detection, flagging `low_confidence=True` rather than guessing.
- Known limitations from real-sample testing are in `memory/KNOWN_ISSUES.md` — read before
  touching `segmentation.py` again.

**`src/analysis/` — deterministic hedging/tone detection. No LLM calls.**

- `hedging_detector.py` — `classify_sentence(text)` labels a sentence `hedged` / `confident` /
  `unmarked` against `skills/earnings-call-analysis/reference/hedging-lexicon.md` (data, not
  hardcoded — parsed at runtime). Sourced from Hyland (1998) + Loughran & McDonald (2011), full
  citations in the lexicon file.
- **Still not wired into extraction** — claims carry no hedge label yet. Still deliberately
  deferred (see Immediate next step); hasn't blocked anything built so far.

**`src/extraction/` — claim extraction. The first LLM-calling stage.**

- `claim_extractor.py` — `extract_claims(turns, client=None, model=DEFAULT_MODEL, max_tokens=8192,
  usage_logger=None)` calls Claude once per transcript, using the `earnings-call-analysis` skill
  (SKILL.md + claim-categories.md, stitched into the system prompt) as instructions, with
  structured outputs for valid JSON. `DEFAULT_MODEL = "claude-haiku-4-5"` — cheapest/fastest
  tier, bounded extraction task not a judgment call (DECISIONS.md).
- `Category` (the 6-value claim-category `Literal` type) is now **public** — was `_Category`,
  renamed so `src/eval/` and `src/revision/` can both import and reuse it instead of redefining
  it, since both need the same category enum in their own structured-output schemas.
- Every claim is verified programmatically before being returned (`source_quote` must be an
  exact transcript substring) — CLAUDE.md's anti-hallucination contract enforced in code, not
  just prompted for. Every call produces a `TokenUsage(stage="extraction", ...)`.
- 14 tests, all against a fake Anthropic client — no real API calls in the automated suite.

**`src/eval/` — faithfulness, coverage, and consistency checks against a draft claims list.**

- `faithfulness_check.py` — deterministic. `check_faithfulness(claims, turns)` re-verifies every
  `source_quote`, with whitespace/unicode-punctuation normalization (curly quotes, dash variants
  seen in real transcript PDFs) but no fuzzy matching. Returns per-claim pass/fail + reason and
  an overall `faithfulness_rate`.
- `coverage_check.py` — deterministic. `check_coverage(claims, turns)` flags a section
  (`Prepared Remarks` / `Q&A`) that exists in the transcript but produced zero claims; a section
  absent from the source entirely is correctly not flagged.
- `consistency_check.py` — the one check that calls an LLM, only for claims in
  `JUDGMENT_CALL_CATEGORIES = {risk_factors, hedging_tone}`. `assess_consistency(claim)`
  implements DECISIONS.md's adaptive N=2->5 sampling on `claude-opus-5` (the strongest tier,
  deliberately — see DECISIONS.md's two entries on why). 1-5 integer scale ("materiality" /
  "framing"); ≤1-point disagreement between the first 2 samples stops there as `stable=True`;
  wider disagreement escalates to 5 and reports `median` + `range_low`/`range_high` — never a
  confidence interval. Thinking is explicitly disabled for this call (see Known bugs below).
- `eval_harness.py` — `run_eval(claims, turns, client=None, ...)` ties all three into one
  `EvalReport`; skips constructing an API client entirely when no judgment-call claims exist.
- 25 tests, all against fake clients — no real API calls in the automated suite.

**`src/revision/` — targeted correction of only the claims eval flagged. The second/last
LLM-calling stage that touches claims (report generation, next, is read-only over claims).**

- `reviser.py` — `revise_claims(claims, eval_report, turns, client=None, model=REVISION_MODEL,
  ...)`. Identifies exactly two failure kinds worth sending back: (1) `unfaithful_quote` — any
  claim `faithfulness_check` flagged; (2) `high_variance_judgment` — a consistency result that
  escalated to 5 samples *and* whose final spread stayed ≥`HIGH_VARIANCE_RANGE_THRESHOLD` (2) —
  an escalation that converged tightly by sample 5 isn't revised. A claim flagged by *both*
  checks gets one combined revision call, not two. Never regenerates the whole draft — per
  DECISIONS.md's targeted-revision entry, this is the whole point.
- Uses `REVISION_MODEL = "claude-opus-5"` — the strongest tier, same reasoning as
  `consistency_check.JUDGMENT_MODEL` but its own separate constant (each stage owns its model
  choice independently even though the value currently matches). Unlike consistency-check's
  trivial 1-5 scoring task, **thinking is deliberately left on** here — revision genuinely
  benefits from reasoning about *why* something failed (confirmed live: the discard-case call
  below used 1,095 output tokens of real reasoning vs. 170 for the straightforward correction).
- The model can respond `corrected` (with a fixed `claim_text`/`category`/`source_quote`/
  `confidence_flag`) or `discard` (the claim genuinely isn't salvageable) — a discriminated-union
  structured-output schema (`_CorrectedClaim` | `_DiscardedClaim`), not a single fixed shape.
  Revision never re-attributes a claim to a different `source_turn_number`.
- A claim citing a nonexistent turn is auto-discarded **without** spending an API call — there's
  no transcript text to revise against.
- After applying corrections/discards, **re-runs `check_faithfulness` on the revised claims
  list** and returns it as `post_revision_faithfulness` — proof the fix actually worked, not
  just that a new answer was produced (this was an explicit requirement, not just a nice-to-have).
- 16 tests in `tests/test_reviser.py` (89 total across the whole suite, all passing), all against
  a fake Anthropic client.

**Live-tested end-to-end twice this session** (real Anthropic API, 6 turns of the Meta
transcript each time):

1. **2026-08-12** — ingestion -> extraction -> eval. One claim's `source_quote` deliberately
   corrupted; faithfulness check caught it (`rate=0.980`, the other 50 of 51 passed). Coverage
   check found a real, legitimate gap: zero claims from the tested Q&A turns (correct — that
   Q&A content was speculative and non-numeric, nothing genuinely checkable there). Consistency
   check on the one `risk_factors` claim present stayed stable (scored 4, 4). Cost: ~4 cents.
2. **2026-08-13** — full loop: ingestion -> extraction -> eval -> revision -> re-verify. Same
   corruption technique for the unfaithful-quote case; a synthetic (clearly labeled) high-variance
   `ConsistencyResult` injected for the real `risk_factors` claim to exercise the second revision
   path with a real API call too. Both handled correctly: the unfaithful claim was corrected —
   model located the actual verbatim quote in the turn and replaced the fabricated one; the
   high-variance claim was **discarded**, with the model reasoning that the quote was verbatim
   but "generic, non-quantified forward-looking boilerplate" that couldn't be reframed into a
   genuinely material, checkable claim. Post-revision faithfulness: **60/60 (100%)**, up from
   60/61 pre-revision. Cost: extraction $0.075 + eval $0.014 + revision $0.046 ≈ **$0.135** total.

**Three real bugs found and fixed via live testing this session** (all documented in detail,
with regression tests, in `memory/KNOWN_ISSUES.md`'s Resolved section — read that before
touching any LLM-calling module in this repo):

1. Extraction's default `max_tokens` (4096) truncated real output mid-JSON; the SDK's resulting
   `pydantic.ValidationError` propagated raw instead of a clear `ClaimExtractionError`. Fixed:
   default raised to 8192, the call wrapped to convert this into an actionable error.
2. Consistency-check judgment calls on `claude-opus-5` returned **completely empty** responses —
   Opus 5 has extended thinking on by default, and `max_tokens` caps thinking + answer text
   *combined*, so `max_tokens=512` let the model spend its whole budget thinking and never write
   the answer. Fixed by explicitly disabling thinking for that trivial scoring task.
3. (Not a bug, but the direct lesson from #2 applied proactively): `reviser.py` needed the
   *opposite* fix — thinking left on (genuinely useful here) but `max_tokens` raised to 4096 up
   front, specifically because #2 had already taught this codebase what happens when a
   thinking-by-default model's budget is set too small. Live-tested clean on the first attempt.

Everything else (report generation) is still just scaffolding — empty package, no logic.

## What's in progress

Nothing actively. Extraction, eval, and revision are all functionally complete for what Phase 1
needs. Hedging detection still isn't wired into extraction — a small, non-blocking gap.

## Immediate next step

Two reasonable candidates:

1. **Report generation** (ROADMAP.md Phase 1's last unchecked core item) — categorized claims
   with citations, an eval appendix (faithfulness rate, consistency variance ranges — explicitly
   not confidence intervals), Markdown export. This is the last piece needed to close Phase 1's
   core loop (ingestion -> extraction -> eval -> revision -> report).
2. **`src/pipeline.py` CLI** (still a stub) — wire everything built so far into one runnable,
   inspectable flow instead of the one-off manual test scripts used to live-test each stage.

Wiring `src/analysis/hedging_detector.py` into extraction (each claim carrying a hedge label) is
still a smaller, independent gap that can slot in whenever — not blocking either of the above.

## Blocked on

Nothing currently. `.env` has a real `ANTHROPIC_API_KEY` (gitignored) — extraction, eval, and
revision have all been live-tested against it successfully.

## Environment / setup status

- [ ] Virtual environment created (dev has been running against a global Python 3.11.4 install
      so far — worth formalizing; environment now has pymupdf, anthropic, pydantic, pytest,
      python-dotenv installed globally)
- [x] `requirements.txt` populated (anthropic>=0.121.0, pydantic>=2.0.0)
- [x] `.env` configured with a real API key
- [x] Sample transcript(s) added to `data/sample_transcripts/` (2 real PDFs, see `SOURCES.md`)
- [x] First real pipeline run attempted — full loop (ingestion -> extraction -> eval ->
      revision -> re-verify) against the live Anthropic API, on 6 turns of the Meta transcript.
      Not yet run through a full transcript or wired into `src/pipeline.py`'s CLI (still a stub).

## Quick orientation for whoever (human or Claude Code) is picking this up

Read `memory/OVERALL_PROJECT.md` for what this is and isn't. Read `memory/ROADMAP.md` for the
phased plan. Read `memory/DECISIONS.md` for architectural reasoning already settled — including
why `claude-opus-5` (not a cheaper model) was chosen and explicitly re-confirmed, with real cost
numbers, for both judgment-call consistency checking and revision — so you don't re-debate
settled questions. Read `memory/KNOWN_ISSUES.md` before modifying `src/ingestion/segmentation.py`,
`src/extraction/claim_extractor.py`, `src/eval/consistency_check.py`, or
`src/revision/reviser.py` specifically — real-world edge cases and three real bugs (all found via
live testing, all fixed with regression tests) are already documented there, including the
thinking-vs-max_tokens interaction that's now been hit once and proactively avoided once.

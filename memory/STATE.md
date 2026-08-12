# STATE.md

**Last updated:** 2026-08-12
**Current phase:** Phase 1 — core pipeline. Ingestion, hedging detection, claim extraction, and
the eval harness (faithfulness + coverage + consistency) are all built and working. Revision
pass and report generation are next.

This file always reflects *current reality only*. Don't leave stale entries — if something
described here stops being true, overwrite it, don't append. History belongs in DECISIONS.md,
not here.

## What actually works right now

**`src/ingestion/` — deterministic PDF loading + speaker-turn segmentation. No LLM calls.**

- `pdf_loader.load_pdf_text(path)` — extracts text via pymupdf (`import pymupdf`, not the
  deprecated `import fitz`), page by page. Raises `PDFTextExtractionError` for: missing file,
  corrupt/non-PDF file, zero-page PDF, or near-empty text layer (avg <50 chars/page — the
  scanned-transcript case). Returns a `LoadedDocument(source_path, page_count, text)`.
- `segmentation.segment_transcript(text)` — parses raw text into `Turn(turn_number,
  speaker_name, speaker_title, section, text)` objects. Handles two real-world cue styles (see
  the module's docstring): standalone "Name, Title" header lines (Meta's format) and inline
  "Name: text" / "Name, Title: text" cues, including dense transcripts that pack multiple cues
  into one paragraph block with no blank-line separation between them (Assurant's format).
  Locates the Prepared Remarks -> Q&A boundary via (1) an explicit heading like "Question &
  Answer Section", (2) an Operator turn whose text contains Q&A-transition phrasing, or (3) a
  weaker fallback (second Operator turn) — flags `low_confidence=True` with explanatory
  `warnings` if none of those apply, rather than guessing.
- Known limitations from real-sample testing are logged in `memory/KNOWN_ISSUES.md` (regex
  name/title split ambiguity on inconsistently-formatted source text, no OCR, English-only
  Q&A-phrasing detection, etc.) — read that before touching `segmentation.py` again.

**`src/analysis/` — deterministic hedging/tone detection. No LLM calls.**

- `hedging_detector.py` — `classify_sentence(text)` labels a sentence `hedged` / `confident` /
  `unmarked` by matching it against `skills/earnings-call-analysis/reference/hedging-lexicon.md`
  (parsed at runtime — the lexicon is data, not hardcoded in Python). Hedge matches take
  precedence over confident matches when a sentence has both. `analyze_turn(turn_text)`
  sentence-splits a whole turn and classifies each sentence.
- Sourced, not guessed — Hyland (1998)'s hedging-linguistics taxonomy plus Loughran & McDonald
  (2011)'s finance-NLP Strong/Weak Modal and Uncertainty word classes; full citations in the
  lexicon file itself.
- **Still not wired into extraction** — claims currently carry no hedge label. Still a small,
  deliberately-deferred gap (see Immediate next step) — not a blocker for anything built so far.

**`src/extraction/` — claim extraction. The first LLM-calling stage.**

- `claim_extractor.py` — `extract_claims(turns, client=None, model=DEFAULT_MODEL, max_tokens=8192,
  usage_logger=None)` calls Claude once against a whole segmented transcript, using the
  `earnings-call-analysis` skill (`skills/earnings-call-analysis/SKILL.md` +
  `reference/claim-categories.md`, stitched into the system prompt at call time — a
  static-prompt-content skill for a pipeline, not a Claude-Code-native skill) as instructions,
  and structured outputs (`client.messages.parse` + a Pydantic schema) for valid JSON.
  `DEFAULT_MODEL = "claude-haiku-4-5"` — cheapest/fastest tier, per DECISIONS.md's model-tiering
  entry; this is a bounded extraction task, not a judgment call.
- **Every claim is verified programmatically before being returned**: `source_quote` must be an
  exact substring of the transcript turn it cites, or the claim is dropped with a warning — the
  model's own claim of faithfulness is never trusted. This is CLAUDE.md's anti-hallucination
  contract enforced in code.
- Every call produces a `TokenUsage(stage="extraction", model, input_tokens, output_tokens,
  cache_*)` for Phase 2's per-stage cost logging to consume later, via an optional `usage_logger`
  callback — no refactor needed when that's built.
- 14 tests in `tests/test_claim_extractor.py`, all against a fake Anthropic client — no real API
  calls in the automated suite.

**`src/eval/` — faithfulness, coverage, and consistency checks against a draft claims list.**

- `faithfulness_check.py` — fully deterministic, no LLM call. `check_faithfulness(claims, turns)`
  re-verifies every claim's `source_quote` against its cited turn (independent of, and stricter
  than what already happens inside extraction) with whitespace/unicode-punctuation normalization
  (curly quotes, multiple dash widths seen in real transcript PDFs) but no fuzzy matching.
  Returns a `FaithfulnessReport` with per-claim pass/fail + reason, and an overall
  `faithfulness_rate`.
- `coverage_check.py` — fully deterministic, no LLM call. `check_coverage(claims, turns)` flags
  any section (`Prepared Remarks` / `Q&A`) that's present in the transcript but produced zero
  claims. A section that doesn't exist in the source at all (e.g. a transcript with no Q&A) is
  correctly *not* flagged — only genuine silent-skip cases are.
- `consistency_check.py` — the one check that calls an LLM, and only for claims in
  `JUDGMENT_CALL_CATEGORIES = {risk_factors, hedging_tone}` (raw extraction should already be
  stable, so it isn't re-sampled). `assess_consistency(claim)` implements DECISIONS.md's adaptive
  N=2->5 sampling on `claude-opus-5` (the strongest tier — deliberately, see DECISIONS.md's
  model-tiering entry and its 2026-08-12 reconsideration-and-confirmation entry): samples 2
  scores (1-5 integer scale — "materiality" for risk_factors, "framing" for hedging_tone); if
  they differ by ≤1 point (`AGREEMENT_THRESHOLD`), stops and reports `stable=True`; otherwise
  escalates to 5 total and reports `median` + `range_low`/`range_high` — explicitly never framed
  as a confidence interval, per DECISIONS.md.
- `eval_harness.py` — `run_eval(claims, turns, client=None, ...)` ties all three into one
  `EvalReport`. Skips constructing an API client entirely when no judgment-call claims are
  present, so it works credential-free on claims lists that don't need consistency checking.
- 25 tests across `tests/test_faithfulness_check.py`, `tests/test_coverage_check.py`,
  `tests/test_consistency_check.py`, `tests/test_eval_harness.py` (75 total across the whole
  suite, all passing) — all against fake clients, no real API calls in the automated suite.

**Live-tested end-to-end on 2026-08-12** (real Anthropic API, 6 turns of the Meta transcript,
ingestion -> extraction -> eval): 51 verified claims extracted; one claim's `source_quote` was
deliberately corrupted before running eval to confirm the faithfulness check actually catches
it — it did (`faithfulness_rate=0.980`, the corrupted claim flagged by name with a clear reason,
the other 50 passed). Coverage check found a real, legitimate gap in this small sample: all 51
claims traced to Prepared Remarks, zero to Q&A — correct, since the tested Q&A turns (an
analyst question plus a speculative, non-numeric answer about future AI product plans) had
little genuinely checkable content, and extraction correctly didn't manufacture claims from it.
Consistency check ran on the one `risk_factors` claim present, scored 4 and 4 on both initial
samples, stayed stable at N=2. Total live-test cost across extraction + eval: roughly 4 cents.

**Two real bugs found and fixed via live testing this session** (both documented in detail, with
regression tests, in `memory/KNOWN_ISSUES.md`'s Resolved section):
1. Extraction's default `max_tokens` (4096) truncated real output mid-JSON; the SDK's resulting
   `pydantic.ValidationError` propagated raw instead of the intended `ClaimExtractionError`.
   Fixed: default raised to 8192, the call wrapped to convert this into a clear error.
2. Consistency-check judgment calls on `claude-opus-5` returned completely empty responses —
   different root cause from #1: Opus 5 has extended thinking on by default, and `max_tokens`
   caps thinking + answer text combined, so a small `max_tokens=512` let the model spend its
   whole budget thinking and never write the JSON answer. Fixed by explicitly disabling thinking
   for this task (correct regardless of the bug — a 1-5 score doesn't need deep reasoning).

Everything else (revision, report) is still just scaffolding — empty packages, no logic.

## What's in progress

Nothing actively. Extraction and eval are both functionally complete for what Phase 1 needs.
Hedging detection still isn't wired into extraction (see next step) — a small, non-blocking gap.

## Immediate next step

Three reasonable candidates:

1. **Wire `src/analysis/hedging_detector.py` into extraction** — each `ExtractedClaim` should
   carry a deterministic hedge label. Small, no new API calls.
2. **Targeted revision pass** (ROADMAP.md Phase 1) — take the eval harness's output (failed
   faithfulness checks, low-materiality-consistency claims, coverage gaps) and correct only the
   flagged claims, not a full regeneration, per DECISIONS.md's targeted-revision entry.
3. **`src/pipeline.py` CLI** (still a stub) — wire ingestion -> extraction -> eval into one
   runnable, inspectable flow instead of the current one-off manual test scripts used to
   live-test each stage so far.

## Blocked on

Nothing currently. `.env` has a real `ANTHROPIC_API_KEY` (gitignored) — both extraction and eval
have been live-tested against it successfully.

## Environment / setup status

- [ ] Virtual environment created (dev has been running against a global Python 3.11.4 install
      so far — worth formalizing; environment now has pymupdf, anthropic, pydantic, pytest,
      python-dotenv installed globally)
- [x] `requirements.txt` populated (anthropic>=0.121.0 — pinned up from the original >=0.34.0
      once `client.messages.parse`/structured outputs turned out to need a much newer SDK;
      pydantic>=2.0.0 added since both `claim_extractor.py` and `consistency_check.py` import it
      directly)
- [x] `.env` configured with a real API key
- [x] Sample transcript(s) added to `data/sample_transcripts/` (2 real PDFs, see `SOURCES.md`)
- [x] First real pipeline run attempted — ingestion -> segmentation -> extraction -> eval
      end to end, against the live Anthropic API, on 6 turns of the Meta transcript (see above).
      Not yet run through a full transcript or wired into `src/pipeline.py`'s CLI (still a stub).

## Quick orientation for whoever (human or Claude Code) is picking this up

Read `memory/OVERALL_PROJECT.md` for what this is and isn't. Read `memory/ROADMAP.md` for the
phased plan — short version: earnings call transcripts first (no tables, proves the full
pipeline), 10-Q second (adds table extraction + numeric cross-check), 10-K and cross-document
comparison later. Read `memory/DECISIONS.md` for the reasoning behind that sequencing and other
architectural choices already made (including two entries specifically about *why*
`claude-opus-5` — not a cheaper model — was chosen and re-confirmed for judgment-call
consistency checking, with real cost numbers), so you don't re-debate settled questions. Read
`memory/KNOWN_ISSUES.md` before modifying `src/ingestion/segmentation.py`,
`src/extraction/claim_extractor.py`, or `src/eval/consistency_check.py` specifically —
real-world edge cases and two real bugs (both found via live testing, both fixed with regression
tests) are already documented there.

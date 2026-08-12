# STATE.md

**Last updated:** 2026-08-12
**Current phase:** Phase 1 — core pipeline. Ingestion, hedging detection, and claim extraction
(the first LLM-calling stage) are all built and working. Eval harness is next.

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
  (parsed at runtime from that file's `## bucket` / `### category` / `- phrase` structure — the
  lexicon is data, not hardcoded in Python; edit the `.md` file to change phrases). Hedge matches
  take precedence over confident matches when a sentence has both. `analyze_turn(turn_text)`
  sentence-splits a whole turn and classifies each sentence.
- The lexicon itself is sourced, not guessed — Hyland (1998)'s hedging-linguistics taxonomy plus
  Loughran & McDonald (2011)'s finance-NLP Strong/Weak Modal and Uncertainty word classes, with
  full citations in the lexicon file's own "Where this comes from" section. See DECISIONS.md for
  why those two sources and why hedging detection got its own `src/analysis/` module rather than
  living in `ingestion/` or `extraction/`.
- **Not yet wired into extraction** — claims currently carry no hedge label. That wiring is the
  next small piece of work, not yet done (see Immediate next step).

**`src/extraction/` — claim extraction. The first (and so far only) LLM-calling stage.**

- `claim_extractor.py` — `extract_claims(turns, client=None, model=DEFAULT_MODEL, max_tokens=8192,
  usage_logger=None)` calls Claude once against a whole segmented transcript, using the
  `earnings-call-analysis` skill (`skills/earnings-call-analysis/SKILL.md` +
  `reference/claim-categories.md`, loaded and stitched into the system prompt at call time — this
  is a static-prompt-content skill for a pipeline, not a Claude-Code-native skill) as
  instructions, and structured outputs (`client.messages.parse` + a Pydantic schema) to
  guarantee valid JSON. `DEFAULT_MODEL = "claude-haiku-4-5"` — cheapest/fastest tier, per
  DECISIONS.md's model-tiering entry; this is a bounded extraction task, not a judgment call.
- **Every claim is verified programmatically before being returned**: `source_quote` must be an
  exact substring of the transcript turn it cites, or the claim is dropped with a warning (see
  `_verify_claims`) — the model's own claim of faithfulness is never trusted. This is the
  anti-hallucination contract from CLAUDE.md enforced in code, not just prompted for.
- Every call produces a `TokenUsage(stage="extraction", model, input_tokens, output_tokens,
  cache_*)` — the hook Phase 2's per-stage cost logging (ROADMAP.md) will consume via the
  `usage_logger` callback param, with no refactor needed when that's built.
- **Live-tested against real API calls** (not just mocks) on 2026-08-12, 6 turns of the real Meta
  transcript: 60 claims extracted, 54 verified (6 dropped for inexact quoting — the verification
  step working as intended, not a bug). Cost: 8,074 input + 5,620 output tokens ≈ **$0.036** for
  6 turns; a full ~35-turn transcript would run roughly 15-20 cents. Category coverage looked
  correct across `financial_performance`, `guidance`, `segment_performance`, `risk_factors`, and
  `non_gaap_vs_gaap` in that one test — `hedging_tone` (the rare category, see
  `claim-categories.md`) wasn't exercised since none of the tested turns warranted it.
- Found and fixed one real bug during that live test: the SDK's default `max_tokens` (4096)
  truncated real output mid-JSON, and the resulting `pydantic.ValidationError` propagated raw
  instead of the intended `ClaimExtractionError` (`client.messages.parse()` never returns a
  `response` object on this failure path, so there's nothing to inspect `stop_reason` on). Fixed:
  default raised to 8192, `messages.parse()` now wrapped to convert this into a clear
  `ClaimExtractionError`. Full writeup and regression test pointer in `memory/KNOWN_ISSUES.md`
  (Resolved section).
- 14 tests in `tests/test_claim_extractor.py` (50 total across the whole suite, all passing) —
  all against a fake Anthropic client (no real API calls in the test suite itself, so `pytest`
  runs without credentials); the live-API sanity check above was a one-off manual run, not part
  of the automated suite.

Everything else (eval, revision, report) is still just scaffolding — empty packages, no logic.

## What's in progress

Nothing actively. Extraction is functionally complete for what Phase 1 needs, but hedging
detection isn't wired into it yet (see next step) — a small gap, not a blocker for building eval.

## Immediate next step

Two candidates, either is reasonable to pick up next:

1. **Wire `src/analysis/hedging_detector.py` into extraction** — each `ExtractedClaim` should
   carry a hedge label (call `classify_sentence`/`analyze_turn` on the claim's `source_quote` or
   `claim_text`). Small, deterministic, no new API calls.
2. **Eval harness v1** (ROADMAP.md Phase 1) — faithfulness check is already partly done at
   extraction time (`_verify_claims`'s exact-substring check); the harness still needs coverage
   checking and the adaptive N=2->5 consistency-sampling design from DECISIONS.md for
   judgment-call categories.

Either way, `src/pipeline.py` (still a stub) will eventually need to wire ingestion ->
hedging-tagged extraction -> eval into one runnable CLI flow.

## Blocked on

Nothing currently. `.env` now exists locally with a real `ANTHROPIC_API_KEY` (gitignored, not
committed) — extraction has been live-tested against it successfully.

## Environment / setup status

- [ ] Virtual environment created (dev has been running against a global Python 3.11.4 install
      so far — worth formalizing, environment now has pymupdf, anthropic, pydantic, pytest,
      python-dotenv installed globally)
- [x] `requirements.txt` populated (anthropic>=0.121.0 — pinned up from the original >=0.34.0
      once `client.messages.parse`/structured outputs turned out to need a much newer SDK;
      pydantic>=2.0.0 added since `claim_extractor.py` imports it directly)
- [x] `.env` configured with a real API key
- [x] Sample transcript(s) added to `data/sample_transcripts/` (2 real PDFs, see `SOURCES.md`)
- [x] First real pipeline run attempted — ingestion -> segmentation -> extraction end to end,
      against the live Anthropic API, on 6 turns of the Meta transcript (see above). Not yet
      run through a full transcript or wired into `src/pipeline.py`'s CLI (still a stub).

## Quick orientation for whoever (human or Claude Code) is picking this up

Read `memory/OVERALL_PROJECT.md` for what this is and isn't. Read `memory/ROADMAP.md` for the
phased plan — short version: earnings call transcripts first (no tables, proves the full
pipeline), 10-Q second (adds table extraction + numeric cross-check), 10-K and cross-document
comparison later. Read `memory/DECISIONS.md` for the reasoning behind that sequencing and other
architectural choices already made, so you don't re-debate settled questions. Read
`memory/KNOWN_ISSUES.md` before modifying `src/ingestion/segmentation.py` or
`src/extraction/claim_extractor.py` specifically — real-world edge cases and one real bug (found
via live testing, now fixed) are already documented there.

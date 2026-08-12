# STATE.md

**Last updated:** 2026-08-12
**Current phase:** Phase 1 — core pipeline. Ingestion (deterministic) done; extraction is next.

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
- Both modules are pure functions, fully unit tested — see `tests/test_pdf_loader.py` and
  `tests/test_segmentation.py` (15 tests, all passing). Tested against two real, differently-
  formatted transcripts in `data/sample_transcripts/` (provenance in that dir's `SOURCES.md`)
  plus synthetic edge cases (no cues at all, no Q&A boundary, explicit heading, front-matter
  skipping).
- Known limitations from real-sample testing are logged in `memory/KNOWN_ISSUES.md` (regex
  name/title split ambiguity on inconsistently-formatted source text, no OCR, English-only
  Q&A-phrasing detection, etc.) — read that before touching `segmentation.py` again.

Everything else (extraction, eval, revision, report, the skill itself) is still just scaffolding
— empty packages / stub files, no logic.

## What's in progress

Nothing actively — ingestion is complete for what Phase 1 needs from it.

## Immediate next step

`skills/earnings-call-analysis/SKILL.md` — the claim-extraction skill (first LLM-calling stage).
Per ROADMAP.md Phase 1: structured JSON output, mandatory source citation (speaker + turn number,
which `segment_transcript`'s `Turn.turn_number` now provides directly) on every extracted claim.
Reference files `hedging-lexicon.md` and `claim-categories.md` need real content too (currently
stubs).

## Blocked on

`.env` still doesn't exist (only `.env.example`) — needed before extraction can make real API
calls. Not a blocker for ingestion work (no LLM calls there) but will be the first thing needed
once extraction starts.

## Environment / setup status

- [ ] Virtual environment created (dev has been running against a global Python 3.11.4 + pymupdf
      install so far — worth formalizing before extraction work adds more dependencies)
- [x] `requirements.txt` populated
- [ ] `.env` configured with API key
- [x] Sample transcript(s) added to `data/sample_transcripts/` (2 real PDFs, see `SOURCES.md`)
- [x] First pipeline run attempted (ingestion stage only, via pytest — not yet via
      `src/pipeline.py`, which is still a stub)

## Quick orientation for whoever (human or Claude Code) is picking this up

Read `memory/OVERALL_PROJECT.md` for what this is and isn't. Read `memory/ROADMAP.md` for the
phased plan — short version: earnings call transcripts first (no tables, proves the full
pipeline), 10-Q second (adds table extraction + numeric cross-check), 10-K and cross-document
comparison later. Read `memory/DECISIONS.md` for the reasoning behind that sequencing and other
architectural choices already made, so you don't re-debate settled questions. Read
`memory/KNOWN_ISSUES.md` before modifying `src/ingestion/segmentation.py` specifically — several
real-world formatting edge cases are already documented there.

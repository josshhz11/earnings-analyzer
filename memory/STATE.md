# STATE.md

**Last updated:** 2026-08-12
**Current phase:** Phase 0 — project scaffolding (complete) → Phase 1 implementation (next)

This file always reflects *current reality only*. Don't leave stale entries — if something
described here stops being true, overwrite it, don't append. History belongs in DECISIONS.md,
not here.

## What actually works right now

Nothing runs yet — scaffolding is complete but no pipeline logic exists. The full directory
structure is in place:

- `skills/earnings-call-analysis/SKILL.md` + `reference/hedging-lexicon.md` +
  `reference/claim-categories.md` — stubs, built out in Prompt 3.
- `src/{ingestion,extraction,eval,revision,report}/` — empty packages (`__init__.py` only).
- `src/pipeline.py` — CLI stub, argument-parses `--input` then raises `NotImplementedError`.
- `tests/`, `data/sample_transcripts/`, `data/cache/` — empty, `.gitkeep`'d.
- `requirements.txt` (pymupdf, anthropic, pytest, python-dotenv), `.env.example`, `.gitignore`
  all populated.

## What's in progress

Nothing — scaffolding (Prompt 0) is the only work done so far.

## Immediate next step

Run Prompt 1 (repo scaffolding follow-up, if any) or proceed directly to Prompt 2 — deterministic
ingestion: PDF → speaker-tagged transcript segments (Prepared Remarks vs. Q&A, speaker name/title
per turn), per ROADMAP.md Phase 1's first checklist item. No LLM calls in this stage.

## Blocked on

Nothing currently. Note: `.env` has not been created yet (only `.env.example` exists) — will be
needed before any LLM-calling stage (extraction onward) can run, but ingestion doesn't need it.

## Environment / setup status

- [ ] Virtual environment created
- [x] `requirements.txt` populated
- [ ] `.env` configured with API key
- [ ] Sample transcript(s) added to `data/sample_transcripts/`
- [ ] First pipeline run attempted

## Quick orientation for whoever (human or Claude Code) is picking this up

Read `memory/OVERALL_PROJECT.md` for what this is and isn't. Read `memory/ROADMAP.md` for the
phased plan — short version: earnings call transcripts first (no tables, proves the full
pipeline), 10-Q second (adds table extraction + numeric cross-check), 10-K and cross-document
comparison later. Read `memory/DECISIONS.md` for the reasoning behind that sequencing and other
architectural choices already made, so you don't re-debate settled questions.

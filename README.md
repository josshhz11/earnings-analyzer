# Earnings Analyzer

An agentic pipeline that extracts, verifies, and reports on claims made in earnings call
transcripts — built as a work sample combining agentic AI engineering (extraction, eval
harness, self-critique/revision loop) with financial-document literacy.

**v1 scope:** earnings call transcripts only, single document, PDF upload. No cross-document
comparison, no SEC filings yet, no auth. See `memory/ROADMAP.md` for what comes after v1 and
why it's sequenced that way.

## Why this exists

Full reasoning in `memory/OVERALL_PROJECT.md`, but briefly: this is a deliberate pivot from an
earlier "AI resume reviewer" concept, kept for the same underlying architecture (agentic
extraction → eval harness → generate-critique-revise) but applied to a domain where claims are
numeric and source-verifiable rather than subjective judgment calls — which makes the
faithfulness-checking genuinely more rigorous, and gives the project relevance to
finance/quant-track job applications, not just AI-agentic roles.

## Pipeline stages

1. **Ingestion** — PDF → structured, speaker-tagged transcript segments.
2. **Extraction** — an LLM skill pulls out categorized, source-cited claims (financial
   performance, guidance, risk factors, hedging/tone).
3. **Eval harness** — faithfulness check (does every claim's cited quote actually appear in the
   source), consistency check (repeated sampling + variance reporting on judgment-call
   categories), coverage check (were all sections processed).
4. **Revision** — flagged issues get corrected and re-verified, not blanket-regenerated.
5. **Report** — category-organized claims with citations, an eval appendix showing faithfulness
   rate and variance ranges, exportable to Markdown/PDF.

## Quickstart

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
python src/pipeline.py --input data/sample_transcripts/example.pdf
```

This runs the full pipeline via the CLI inspection tool — the intended way to develop and
validate this project before any web UI exists.

## Project memory (for anyone, human or Claude Code, picking this up)

This repo uses a `memory/` folder as a persistent project log, since context doesn't carry over
between separate work sessions:

- `memory/OVERALL_PROJECT.md` — what this is, scope, non-goals, architecture. Rarely changes.
- `memory/STATE.md` — what's actually built and working *right now*. Changes every session —
  read this first if you're picking the project back up.
- `memory/DECISIONS.md` — append-only log of real decisions made and why.
- `memory/KNOWN_ISSUES.md` — bugs, limitations, deferred items.
- `memory/ROADMAP.md` — the phased build plan.

If you're using Claude Code on this repo, `CLAUDE.md` instructs it to read and update these
automatically each session.

# CLAUDE.md

Instructions for Claude Code working in this repo. Read this first, every session.

## Session start protocol

Before doing anything else in a new session:
1. Read `memory/STATE.md` — this tells you exactly where the last session left off.
2. Read `memory/OVERALL_PROJECT.md` — this tells you what this project is and isn't, so you
   don't reinvent scope decisions that were already made.
3. Skim `memory/KNOWN_ISSUES.md` for anything relevant to what you're about to work on.
4. Only then start the task the user gives you.

## Session end protocol

Before ending a work session (or when the user says "wrap up" / "update memory"):
1. Update `memory/STATE.md` — overwrite it, it should always reflect *current* reality, not
   history. Be specific: what runs right now, what's half-built, what the exact next step is.
2. If you made a real architectural or scoping decision during this session (not just a small
   implementation detail), append it to `memory/DECISIONS.md` with a date and the reasoning —
   never edit past entries, only append.
3. If you hit a bug you're not fixing now, or found a limitation worth remembering, add it to
   `memory/KNOWN_ISSUES.md`.
4. If the roadmap changed (a phase got reordered, scope got cut, something new got added),
   update `memory/ROADMAP.md`.

Don't skip this because the session felt small — STATE.md going stale is the single biggest
failure mode of this whole memory system.

## Project identity

This is **Earnings Analyzer** — an agentic pipeline that extracts and verifies claims from
earnings call transcripts (v1), with 10-Q filing support planned as v2. Full context in
`memory/OVERALL_PROJECT.md`. Full phased plan in `memory/ROADMAP.md`.

## Core engineering principles for this repo (non-negotiable, don't relitigate each session)

- **Deterministic before LLM.** Anything checkable with code (regex, structure detection,
  numeric computation) is code, not a model call. Never reach for an LLM call to do something
  a parser or a rule can do — this is a cost and reliability principle, not a style preference.
- **Every claim the pipeline outputs must carry a source citation** (speaker + turn number for
  transcripts, Item/table-cell for filings later). No un-sourced claims, ever — this is the
  anti-hallucination contract for the whole system.
- **Model tiering.** Cheapest/fastest model for bounded extraction tasks. Reserve the strongest
  model for genuine judgment calls (risk materiality, hedging-vs-confidence framing, executive
  summary synthesis). See `memory/DECISIONS.md` for which stages use which tier and why.
- **Variance gets measured, not hidden.** Judgment-call categories get repeated-sampled (see
  `memory/DECISIONS.md` for the adaptive N=2→5 approach) and reported as median + range, never
  a single number dressed up as precise. Deterministic categories get no range — that
  distinction should be visible in every report the pipeline produces.
- **Log token usage per pipeline stage.** Every LLM call should be tagged with which stage
  produced it (extraction / eval / revision / summary) so cost can be broken down and optimized
  stage-by-stage, not just totaled. This is a deliberate learning goal for this project, not
  an afterthought — see `memory/OVERALL_PROJECT.md`.
- **Personal inspection tooling before any UI.** Build and use the CLI pipeline runner
  (`src/pipeline.py`) to validate each stage yourself before wrapping anything in a web form.

## Commands

(Fill in once the project has real tooling — placeholders below, update as you set these up)

```
pip install -r requirements.txt        # install deps
python src/pipeline.py --input <path>  # run the full pipeline on a transcript, CLI inspection mode
pytest tests/                           # run tests
```

## Code style

- Python, type-hinted, docstrings on every public function.
- No bare `except:` — catch specific exceptions, especially around PDF parsing and API calls,
  since both fail in predictable, distinct ways that should be handled differently.
- Keep stage boundaries clean (ingestion / extraction / eval / revision / report are separate
  modules with clear inputs and outputs) — this matters because the eval harness needs to be
  able to test each stage independently.

## Where things live

- `skills/` — SKILL.md files for claim extraction (model-invoked, see each SKILL.md for its
  trigger description).
- `src/` — the actual pipeline code, organized by stage.
- `memory/` — this project's persistent memory. Read/write per the protocol above.
- `data/sample_transcripts/` — test inputs. `data/cache/` — gitignored dev-time cache of
  extraction/LLM results so repeated local runs don't repay for unchanged stages.

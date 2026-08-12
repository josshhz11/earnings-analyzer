# ROADMAP.md

Phased plan. Update this when phases get reordered, cut, or added — but keep completed phases
in the file (marked done), don't delete history.

## Phase 1 — Core pipeline on earnings call transcripts (current target)

- [x] Deterministic ingestion: PDF → speaker-tagged transcript segments (Prepared Remarks vs
      Q&A, speaker name/title per turn).
- [x] `skills/earnings-call-analysis/SKILL.md` — claim extraction skill, structured JSON output,
      mandatory source citation (speaker + turn) on every claim.
- [ ] Eval harness v1: faithfulness check (programmatic, quote-matching), coverage check.
- [ ] Consistency check with adaptive N=2→5 sampling on judgment-call categories, median + range
      reporting.
- [ ] Targeted revision pass (only flagged claims get corrected, not full regeneration).
- [ ] Report generation — categorized claims with citations, eval appendix, Markdown export.
- [ ] `src/pipeline.py` CLI tool for personal inspection of every stage's output.
- [ ] Run end-to-end on at least 3 real sample transcripts, sanity-check output by hand.

## Phase 2 — Cost instrumentation

- [ ] Token usage logging per pipeline stage (extraction / eval / revision / summary), tagged
      and queryable, not just a single total.
- [ ] Model tiering implemented per DECISIONS.md (cheap model for extraction, strongest model
      reserved for judgment calls and summary synthesis).
- [ ] Prompt caching for the source document + skill reference files across calls in a single
      pipeline run.
- [ ] Batch API used for all dev-time/inspection runs (not user-facing, not latency-sensitive).
- [ ] Disk-cache extraction/LLM results during local development so repeated debugging runs
      don't repay for unchanged stages.
- [ ] Produce an actual before/after cost number once the above are in — this is meant to
      become a concrete, citable metric, not just a design intention.

## Phase 3 — 10-Q filing support (adds table extraction)

- [ ] Document-type detection (transcript vs. filing) at ingestion.
- [ ] Item-boundary detection for 10-Q sections (MD&A, financial statements, notes).
- [ ] Table extraction with row/column structure preserved (this becomes the ground truth for
      the new numeric cross-check, below).
- [ ] Numeric cross-check: recompute stated percentages/changes from raw table data and compare
      against MD&A narrative claims — flags both extraction errors and genuine discrepancies.
- [ ] `skills/sec-filing-analysis/SKILL.md`, emitting the same claim schema as the transcript
      skill so eval harness code doesn't need to branch on document type.
- [ ] Extend report format to include the numeric cross-check results.

## Phase 4 — 10-K support

- [ ] Only after Phase 3 is solid. Reuse the 10-Q filing pipeline; the main new work is handling
      the larger document (Item 1 Business, more extensive Risk Factors) without a proportional
      blowup in cost — Phase 2's cost work should already be absorbing most of this.

## Phase 5 — Cross-document / cross-period comparison (not scoped in detail yet)

- [ ] This quarter's guidance vs. actuals reported this quarter (did management deliver on what
      they said last time) — the first place a genuinely new, higher-value analytical claim
      becomes possible, versus single-document extraction and verification.
- [ ] Transcript-vs-filing cross-referencing (does what the CEO said on the call match the 10-Q).

## Phase 6 — Web UI (only after the above are stable)

- [ ] Simple upload form, PDF in, pipeline runs, report renders, export button. No auth needed
      unless persistence across sessions becomes a real requirement by this point.

## Explicitly not planned / out of scope indefinitely

- Speech-to-text for live calls — noted as a "later, if we want to be cool" idea, not committed.
- URL ingestion — same, noted but not committed.
- Investment recommendations of any kind — this tool verifies and reports claims, it does not
  and should not generate buy/sell/hold judgments.

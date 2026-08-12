# DECISIONS.md

Append-only log. Never edit or delete past entries — if a decision gets reversed, add a new
entry noting the reversal and why, don't rewrite history. Each entry: date, decision, reasoning.

---

## [SEED] Earnings call transcripts before 10-Q or 10-K

**Decision:** v1 handles earnings call transcripts only. 10-Q is v2. 10-K is deferred
indefinitely past that.

**Reasoning:** Transcripts have no tables and no Item-boundary taxonomy to detect — just
speaker-tagged dialogue. This lets the full pipeline skeleton (ingestion → extraction → eval →
revision → report) get built and debugged on the structurally simplest input, before adding
table extraction and numeric cross-checking as an incremental layer with 10-Q. 10-K was ruled
out for v1 entirely: at 100-200+ pages, most of the extra bulk (Item 1 Business narrative,
exhibits, deep footnote tables) doesn't teach the pipeline anything new, it just adds extraction
surface area and slows iteration while the core loop is still being proven.

---

## [SEED] Median + range, not a formal confidence interval, for variance reporting

**Decision:** Judgment-call categories get repeated-sampled (adaptive N=2→5) and reported as
median + range/spread across runs. This is explicitly *not* called a "95% confidence interval."

**Reasoning:** With N=5-10 samples, a formal CI overstates statistical rigor. Median (not mean)
is more robust to a single outlier run. This directly addresses a documented flaw in
HackerRank's public `interviewstreet/hiring-agent` resume-scoring tool, where the same resume
scored 90/74/88/83 across runs with no variance disclosed — reporting a range instead of a fake
-precise single number is the whole point of this design choice.

---

## [SEED] Adaptive sampling (N=2 first, escalate to 5 only on disagreement)

**Decision:** Don't blanket-run 5 samples on every judgment-call category every time. Run 2
first; if they agree closely, stop and report as stable; escalate to the full 5 only when the
first two disagree meaningfully.

**Reasoning:** Cost optimization. Most categories on most documents are probably stable — paying
for 5 samples every time wastes tokens on categories that didn't need it, without losing the
signal on the ones that actually are noisy (which is the entire point of measuring variance).

---

## [SEED] Deterministic-first: no LLM call for anything checkable by code

**Decision:** Table/number extraction (once 10-Q work starts), speaker-turn segmentation,
hedging-phrase detection, and any other structurally-checkable step is regex/rule-based code,
never an LLM call.

**Reasoning:** Cost and reliability. This mirrors the same principle used in the earlier resume-
project rubric design (mechanical checks were deterministic Python, LLM only for genuine
judgment calls) — every call resolved by code is a call not being paid for, and it's also more
reliable than an LLM re-deriving something that's actually just arithmetic or pattern matching.

---

## [SEED] Model tiering across pipeline stages

**Decision:** Cheapest/fastest available model for bounded extraction tasks (pulling a claim +
category tag out of a text chunk). Reserve the strongest model for genuine judgment calls (risk
materiality ranking, hedging-vs-confidence framing, final executive summary synthesis).

**Reasoning:** Cost optimization, applied more precisely than HackerRank's own pipeline does —
their public repo ships a cheap demo-tier model config while their actual production evaluation
reportedly uses a top-tier model, an undisclosed gap between demo and reality. This project
tiers deliberately and transparently, matching model strength to task difficulty per stage.

---

## [SEED] Targeted revision, not full regeneration

**Decision:** When the eval harness flags specific claims as unfaithful or miscategorized, only
those flagged items get sent back for correction — the whole draft report is never regenerated
from scratch.

**Reasoning:** Cost optimization (why re-pay for the ~90% of a report that already passed eval),
and it's also a more defensible engineering pattern than a blanket regenerate-and-hope approach.

---

## [SEED] Personal CLI inspection tooling before any web UI

**Decision:** Build and use `src/pipeline.py` as a CLI tool to step through and validate every
stage's output (ingestion → draft claims → eval results → revision diff → final report) before
wrapping any of this in a web form.

**Reasoning:** Same build-order discipline used on the earlier resume project — debug the
actual hard part (does the eval harness correctly catch real problems) without a UI layer in
the way, and don't let deployment concerns arrive before the core logic is proven correct.

---

## [SEED] Non-GAAP/GAAP divergence and hedging-language detection as explicit output categories

**Decision:** The report explicitly flags where a call distinguishes GAAP vs. adjusted/non-GAAP
figures, and explicitly flags hedged vs. unqualified language around guidance/claims.

**Reasoning:** These are real, well-understood analyst-scrutiny signals in equity/credit
research (hedged guidance reads as lower management confidence; GAAP/non-GAAP divergence is a
standard area companies get pressed on) — surfacing them explicitly, rather than burying them in
prose, is what makes this tool's output resemble real analyst work rather than a generic
summarizer.

---

## 2026-08-12 — pymupdf chosen over pdfplumber for PDF parsing

**Decision:** `requirements.txt` pins `pymupdf`, not `pdfplumber`, for the ingestion stage.

**Reasoning:** pymupdf is faster and more actively maintained, which matters since ingestion
runs on every pipeline invocation, not just at dev time. It also ships built-in table detection
(`Page.find_tables()`) as of 1.23+, which Phase 3 (10-Q table extraction) will need — picking it
now avoids a library swap when that phase starts, versus reaching for pdfplumber later
specifically for its table-extraction strength. Revisit only if pymupdf's table detection proves
inadequate once Phase 3 actually starts.

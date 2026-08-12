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

---

## 2026-08-12 — Hedging lexicon sourced from Hyland (1998) and Loughran-McDonald (2011), not invented ad hoc

**Decision:** `skills/earnings-call-analysis/reference/hedging-lexicon.md`'s phrase categories
are drawn from two established sources rather than a hand-guessed list: Hyland's linguistics
taxonomy of hedging devices (modal verbs, epistemic verbs, probability adjectives/adverbs,
approximators) for the "Hedging phrases" categories, and Loughran & McDonald's finance-NLP
Master Dictionary word classes — specifically their Strong Modal (will/must/shall) and Weak
Modal (could/may/might/should) categories, plus their Uncertainty word list — for the modal-verb
split between the hedging and confident buckets. Earnings-call-specific boilerplate (forward-
looking-statement caveats) was added separately, drawn from standard SEC disclosure convention,
not from either academic source.

**Reasoning:** Both sources are established, citable references for exactly this kind of
categorization (Loughran-McDonald in particular is the standard word list used in finance/
10-K/earnings-call textual analysis research), so the lexicon has a defensible basis instead of
being an arbitrary list that would need re-justifying later. Full citations and per-category
sourcing are in the lexicon file itself ("Where this comes from" section) so the reasoning stays
next to the data it explains, not just here.

---

## 2026-08-12 — Hedging detection lives in new `src/analysis/`, not `src/ingestion/` or `src/extraction/`

**Decision:** `hedging_detector.py` (deterministic phrase-lexicon matching, no LLM calls) got a
new top-level module, `src/analysis/`, rather than being added to `src/ingestion/` or
`src/extraction/`.

**Reasoning:** Ingestion's job is strictly structural — raw PDF into speaker-tagged turns, with
zero interpretation of what's actually said. Extraction is specifically the LLM-calling
claim-pulling stage. Hedging detection is deterministic *content* analysis: it doesn't parse
document structure (not ingestion) and it isn't a model call (not extraction) — but both the
extraction stage (to tag each claim's hedging status) and the report stage (to surface it) will
need to call it. Giving it its own module keeps CLAUDE.md's stage-boundary-cleanliness principle
intact and gives future deterministic text-analysis utilities (e.g. non-GAAP/GAAP phrase
detection, also planned per OVERALL_PROJECT.md's claim categories) an obvious home instead of
overloading ingestion or extraction with logic that doesn't belong to either.

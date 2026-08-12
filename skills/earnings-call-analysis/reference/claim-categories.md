# Claim Categories

Six categories, matching `memory/OVERALL_PROJECT.md`'s claim rubric. Every extracted claim gets
exactly one of the slugs below as its `category` value — use the slug, not the display name.

## `financial_performance`

Financial results **as stated on the call** — revenue, margins, EPS, cash flow, expenses,
operating income, tax rate, headcount, and similar reported figures. No table cross-check
happens in v1 (transcripts have no tables); that verification arrives with v2's 10-Q work. Only
capture what a speaker actually said, not what you can infer or compute from other numbers.

**Examples:**
- "Q4 total revenue was $48.4 billion, up 21% on both a reported and constant currency basis."
- "Fourth quarter operating income was $23.4 billion, representing a 48% operating margin."
- "We ended the year with over 74,000 employees, up 10% year-over-year."

## `guidance`

Forward-looking statements about future performance — next quarter/year targets, expected
trends, planned investment levels, stated expectations about growth or costs. Includes both
explicit numeric guidance and qualitative forward statements management commits to on the
record.

**Examples:**
- "We now expect full-year adjusted earnings per share growth of low-double digits."
- "We expect to bring online almost 1GW of capacity this year."
- "We remain on track to grow Global Auto adjusted EBITDA for the full year."

## `risk_factors`

Risks, headwinds, uncertainties, or negative factors management discusses — competitive
threats, regulatory exposure, macro headwinds, execution risk, anything framed as something
that could hurt results. Distinct from `guidance`: guidance is what management expects to
happen; risk factors are what could make that expectation wrong.

**Examples:**
- "We face headwinds in the EU and the US that could significantly impact our business and our
  financial results."
- "The new competitor DeepSeek from China puts pressure on our open-source strategy."

## `segment_performance`

Performance broken out by business line, product segment, or geography — anything below the
consolidated/company-wide level. Distinct from `financial_performance`, which is for
company-wide figures.

**Examples:**
- "Global Lifestyle earnings increased 4%, or 6% on a constant-currency basis, year-to-date."
- "In Global Auto, adjusted EBITDA increased 4% year-to-date."
- "WhatsApp now has more than 100 million monthly actives in the US."

## `non_gaap_vs_gaap`

Any point on the call where GAAP and non-GAAP/adjusted figures are explicitly distinguished, or
where a speaker calls out that a figure is adjusted/non-GAAP. This is a real analyst-scrutiny
signal (see `memory/DECISIONS.md`) — capture it whenever the call itself draws the distinction,
even briefly.

**Examples:**
- "During this call we will present both GAAP and certain non-GAAP financial measures."
- "We've achieved 13% adjusted EBITDA growth and 15% adjusted EPS growth, both excluding
  reportable catastrophes."

## `hedging_tone`

Reserve this category for claims that are fundamentally *about* a shift or notable pattern in
how management is framing something — not for tagging the hedge-phrasing of an otherwise
financial/guidance/risk claim. For example: management visibly softening language around a
previously firm commitment, or explicitly caveating a number they'd normally state plainly, is
itself claim-worthy content. This category will be rare — most calls don't contain an explicit,
extractable claim *about* tone itself.

**Do not** use this category as a substitute for phrase-level hedge detection. Every extracted
claim (regardless of category) gets a separate hedged/confident/unmarked label from
`src/analysis/hedging_detector.py` downstream — that is a deterministic phrase-lexicon match
against the claim's source text, not something you assign here. See `memory/DECISIONS.md` for
why that split is deliberate (hedging detection must stay deterministic, not an LLM judgment
call).

**Example (the rare case where this category is the right fit):**
- "Where prior quarters described the buyback program as a firm commitment, this quarter
  management repeatedly qualified it as 'subject to market conditions' — a notable shift in
  framing on the same topic."

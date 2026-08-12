# earnings-call-analysis

**Status:** stub — this file is built out in Prompt 3 (claim extraction skill).

This skill will define the model-invoked claim-extraction step: given a speaker-tagged
transcript segment, extract atomic claims (text, category tag, source turn number, direct
quote for verification) as structured JSON. See `memory/OVERALL_PROJECT.md` for the claim
category rubric and `memory/ROADMAP.md` Phase 1 for what this needs to produce.

Reference material for this skill lives in `reference/`:
- `hedging-lexicon.md` — phrase list for detecting hedged vs. unqualified language.
- `claim-categories.md` — the six claim categories and what belongs in each.

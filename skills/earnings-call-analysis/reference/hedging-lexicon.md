# Hedging Lexicon

Categorized phrase lists for detecting hedged vs. confident/unqualified language in earnings
call statements. This is the single source of truth for `src/analysis/hedging_detector.py` —
the detector parses this file's structure at runtime rather than hardcoding phrases in Python,
so edit this file (not the code) to add, remove, or recategorize phrases.

## Where this comes from

Not invented ad hoc. Drawn from two established sources, adapted to the earnings-call register:

1. **Hyland, K. (1998), *Hedging in Scientific Research Articles*.** The standard linguistics
   taxonomy of hedging devices: modal auxiliary verbs, epistemic (belief/estimation) verbs,
   probability adjectives/adverbs, and approximators. The "Hedging phrases" categories below map
   directly onto this taxonomy.
2. **Loughran, T., & McDonald, B. (2011), "When Is a Liability Not a Liability? Textual
   Analysis, Dictionaries, and 10-Ks," *Journal of Finance*.** The finance-NLP standard for
   this kind of word list (their Master Dictionary is widely used for 10-K/earnings-call textual
   analysis). Two categories borrowed directly: their **Strong Modal** word class (will, must,
   shall — high certainty) informs "Confident phrases > Strong modal verbs" below, and their
   **Weak Modal** class (could, may, might, should) plus their **Uncertainty** word list inform
   "Hedging phrases > Modal verbs of possibility" and "> Uncertainty/approximation markers".

Everything else (the earnings-call-specific boilerplate categories, e.g. forward-looking-
statement language) was drawn from common SEC forward-looking-statement disclosure conventions,
not from either academic source — these are the standard caveat phrases companies use on every
call, easily recognized by anyone who's read a few transcripts.

## Format

Two top-level buckets (`## Hedging phrases`, `## Confident / unqualified phrases`), each broken
into `###` categories, each a flat bullet list of phrases. Matching is case-insensitive and
whole-word/whole-phrase (word-boundary anchored) — see `src/analysis/hedging_detector.py`.
Multi-word phrases are matched as exact substrings with word boundaries at both ends.

## Hedging phrases

### Modal verbs of possibility (Loughran-McDonald "Weak Modal")
- may
- might
- could
- would
- should

### Epistemic verbs of belief/estimation (Hyland)
- we believe
- we expect
- we anticipate
- we estimate
- we project
- we forecast
- we think
- we feel
- appears to be
- seems to be
- suggests that

### Uncertainty / approximation markers (Loughran-McDonald "Uncertainty", Hyland approximators)
- approximately
- roughly
- around
- about
- in the range of
- somewhere between
- give or take
- uncertain
- uncertainty
- unpredictable
- fluctuate
- fluctuation
- variability
- depends on
- depending on

### Conditional / contingency hedges (Hyland)
- subject to
- provided that
- assuming
- contingent on
- contingent upon
- if conditions
- to the extent that

### Probability adjectives and adverbs (Hyland)
- likely
- unlikely
- possible
- possibly
- potentially
- probable
- probably

### Forward-looking-statement boilerplate (SEC disclosure convention)
- forward-looking statements
- actual results may differ materially
- no obligation to update
- based on our current expectations
- based on current assumptions
- to the best of our knowledge

## Confident / unqualified phrases

### Strong modal verbs (Loughran-McDonald "Strong Modal")
- will
- must
- shall

### Assertive factual statements (past-tense realized outcomes)
- delivered
- achieved
- grew
- increased
- decreased
- generated
- reported
- came in at
- exceeded
- beat
- drove
- returned

### Certainty adverbs
- certainly
- clearly
- definitely
- undoubtedly
- without question

### Strong commitment phrases
- we will
- we are committed to
- we remain confident
- we guarantee
- we are confident that

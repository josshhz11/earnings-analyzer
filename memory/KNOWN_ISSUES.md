# KNOWN_ISSUES.md

Bugs, limitations, and deliberately-deferred rough edges. Not a task tracker for planned future
work — that's ROADMAP.md. This is specifically for "this is broken or limited, here's the
current status," so nobody re-discovers the same problem from scratch in a future session.

Entry format:
```
## [STATUS] Short title
**Discovered:** date
**Severity:** low / medium / high
**Description:** what's actually wrong or limited.
**Workaround / status:** what to do about it now, or why it's intentionally left as-is.
```
Status tags: `[OPEN]` not fixed, `[WORKAROUND]` has a workaround in place, `[WONTFIX-V1]`
deliberately deferred past v1, `[RESOLVED]` fixed (keep the entry for history, don't delete it —
move resolved entries to the bottom under a "Resolved" heading rather than removing them).

---

## [OPEN] Speaker cue regex misparses names when source PDF text omits an expected comma
**Discovered:** 2026-08-12, implementing `src/ingestion/segmentation.py`
**Severity:** low
**Description:** The inline-cue pattern (`Name, Title: text`) assumes a comma between the
speaker's name and their role. The real Assurant Q3 2025 transcript sample is internally
inconsistent about this — most Q&A cues read `"Mark Hughes, Analyst, Truist Securities, Inc.:"`
but at least two occurrences read `"Mark Hughes Analyst, Truist Securities, Inc.:"` (no comma
after the surname). Since "Analyst" is itself capitalized, the regex greedily folds it into
`speaker_name` (`"Mark Hughes Analyst"`) instead of `speaker_title`. Confirmed via
`grep -n "Mark Hughes Analyst" data/sample_transcripts/*.pdf` extracted text — this is a
genuine inconsistency in the source document's text layer, not a segmentation bug.
**Workaround / status:** The turn's dialogue text is still captured correctly and attributed to
a turn — only the name/title split is cosmetically wrong for these specific lines, and the same
speaker's other (correctly-formatted) turns still use the clean `"Mark Hughes"` name. Not
fixing for v1: a robust fix would need a dictionary of known role-words (Analyst, President,
CFO, etc.) to detect the missing comma, which is more complexity than this deterministic-regex
approach is meant to carry. Downstream consumers that need to merge same-speaker turns should
not assume `speaker_name` is byte-identical across a whole transcript.

## [OPEN] Standalone-header cue pattern can misfire on a short one-line body sentence
**Discovered:** 2026-08-12, implementing `src/ingestion/segmentation.py`
**Severity:** low (currently theoretical — not observed in either real sample)
**Description:** The no-colon "Name, Title" cue style (used by Meta's transcript format) is only
matched against a block that is exactly one line, isolated by blank lines on both sides — but a
contrived one-line paragraph like `"Susan, thanks so much."` would also match that shape (capital
word + comma + trailing text) if it ever appeared as its own isolated block.
**Workaround / status:** Not fixed — real transcripts consistently only isolate genuine speaker
headers this way (that's *why* the source PDF author put blank lines around them), so this
hasn't fired on either real sample. Documented so a future session doesn't have to re-derive the
risk from scratch if a new sample transcript trips it.

## [OPEN] Section/roster heading lines get silently appended to the adjacent turn's text
**Discovered:** 2026-08-12, implementing `src/ingestion/segmentation.py`
**Severity:** low
**Description:** A heading line that isn't recognized as a Q&A boundary marker (only
`"Question & Answer Section"`-style phrasing is, via `QA_HEADING_RE`) and isn't a speaker cue —
e.g. a stray `"MANAGEMENT DISCUSSION SECTION"` appearing *after* the first turn has already
started — falls through to the "continuation of previous turn" branch and gets appended as if it
were dialogue, polluting that turn's `text`.
**Workaround / status:** Not fixed for v1. Only matters for headings that appear after parsing
has already started (leading front matter before the first turn is handled correctly — see
`test_front_matter_before_first_cue_is_skipped_not_attributed`). Low impact: it's a few extra
words at a turn boundary, not a misattribution.

## [WONTFIX-V1] No OCR — scanned/image-only PDFs are rejected, not processed
**Discovered:** 2026-08-12, implementing `src/ingestion/pdf_loader.py`
**Severity:** medium (blocks a real input type, but deliberately out of scope)
**Description:** `load_pdf_text` raises `PDFTextExtractionError` when a PDF's average
extracted-text-per-page falls below a threshold (50 chars), which is what a scanned transcript
with no text layer looks like. There is no fallback OCR path.
**Workaround / status:** Deliberate v1 scope boundary, consistent with `OVERALL_PROJECT.md`'s
non-goals — user must supply a text-layer PDF. Revisit only if OCR ingestion becomes an actual
stated requirement (not currently on ROADMAP.md).

## [WONTFIX-V1] Q&A boundary detection is English-phrasing-dependent
**Discovered:** 2026-08-12, implementing `src/ingestion/segmentation.py`
**Severity:** low
**Description:** The three-tier Q&A boundary heuristic (explicit heading match, Operator-turn
keyword match, second-Operator-turn fallback) all key off English phrases ("Question and
Answer", "open the floor/lines/call for questions", the literal word "Operator"). A transcript
in another language, or from a vendor using different Q&A-transition phrasing entirely, will
correctly fail closed into `low_confidence=True` with the whole document labeled
`Prepared Remarks` — it won't guess — but it also won't segment the Q&A section at all.
**Workaround / status:** Acceptable for v1 (English-language earnings calls only, consistent with
target scope). No action needed unless non-English transcripts become a stated requirement.

"""Deterministic hedging vs. confident/unqualified language detection.

No LLM calls — per DECISIONS.md, hedging/tone is phrase-lexicon matching, not a model
judgment call. The phrase lists live in
`skills/earnings-call-analysis/reference/hedging-lexicon.md`, not in this file, so the
lexicon can be edited (add/remove/recategorize phrases) without touching code — this
module only knows how to *parse* that file's structure and match its phrases against text.

## Module boundary note

This lives in `src/analysis/`, not `src/ingestion/` or `src/extraction/`. Ingestion is
strictly "raw PDF -> structured speaker turns" (no interpretation of what's *said*).
Extraction is the LLM-calling claim-pulling stage. Hedging detection is deterministic
*content* analysis that both the extraction stage (to tag claims) and the report stage
will want to call — it doesn't belong bolted onto either. `src/analysis/` is the new home
for this and any future deterministic text-analysis utilities (see ROADMAP.md/STATE.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

HEDGED = "hedged"
CONFIDENT = "confident"
UNMARKED = "unmarked"

DEFAULT_LEXICON_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "earnings-call-analysis"
    / "reference"
    / "hedging-lexicon.md"
)

# Maps a lexicon "## <title>" bucket header (lowercased) to its internal bucket key.
_BUCKET_HEADERS = {
    "hedging phrases": "hedging",
    "confident / unqualified phrases": "confident",
}

_SECTION_RE = re.compile(r"^(#{2,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^-\s+(.+)$")

# Splits on sentence-ending punctuation followed by whitespace and a capital
# letter. Deliberately simple/deterministic — no NLP sentence-boundary model.
# Known limitation: abbreviations like "Inc." or "U.S." immediately followed
# by a capitalized word will over-split; see KNOWN_ISSUES.md.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@dataclass(frozen=True)
class LexiconEntry:
    """One phrase from the lexicon file, with the category it was listed under."""

    phrase: str
    category: str


@dataclass(frozen=True)
class Lexicon:
    """Parsed hedging-lexicon.md, plus precompiled match patterns for both buckets."""

    hedging: tuple[LexiconEntry, ...]
    confident: tuple[LexiconEntry, ...]
    hedging_pattern: re.Pattern[str]
    confident_pattern: re.Pattern[str]


@dataclass(frozen=True)
class PhraseMatch:
    """One phrase found in a sentence, with the lexicon category it came from."""

    phrase: str
    category: str


@dataclass(frozen=True)
class HedgeClassification:
    """The hedging classification of a single sentence."""

    text: str
    label: str  # HEDGED, CONFIDENT, or UNMARKED
    hedge_matches: tuple[PhraseMatch, ...]
    confident_matches: tuple[PhraseMatch, ...]


def _build_alternation_pattern(entries: tuple[LexiconEntry, ...]) -> re.Pattern[str]:
    """Compile a case-insensitive, word-boundary-anchored alternation over all phrases.

    Longest phrases first so a multi-word phrase is preferred over a shorter
    phrase that happens to be its prefix, when both start at the same position.
    """
    if not entries:
        # Never matches anything — an empty bucket shouldn't crash matching.
        return re.compile(r"(?!)")
    escaped = sorted((re.escape(e.phrase) for e in entries), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


def parse_lexicon(markdown_text: str) -> Lexicon:
    """Parse hedging-lexicon.md's structure into a Lexicon.

    Expects `## Hedging phrases` / `## Confident / unqualified phrases` bucket
    headers, each containing `### <category>` subsections of `- phrase` bullets.
    Deterministic line-based parsing — see the lexicon file's own "Format" section.

    Raises:
        ValueError: if either bucket ends up with zero phrases, which almost
            always means the file's headers were edited in a way this parser
            no longer recognizes (fail loud rather than silently matching nothing).
    """
    hedging: list[LexiconEntry] = []
    confident: list[LexiconEntry] = []

    current_bucket: Optional[str] = None
    current_category: Optional[str] = None

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()

        section_match = _SECTION_RE.match(line)
        if section_match:
            hashes, title = section_match.groups()
            title_lower = title.strip().lower()
            if len(hashes) == 2:
                current_bucket = _BUCKET_HEADERS.get(title_lower)
                current_category = None
            elif len(hashes) == 3 and current_bucket is not None:
                current_category = title.strip()
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match and current_bucket is not None and current_category is not None:
            phrase = bullet_match.group(1).strip().lower()
            entry = LexiconEntry(phrase=phrase, category=current_category)
            if current_bucket == "hedging":
                hedging.append(entry)
            else:
                confident.append(entry)

    if not hedging:
        raise ValueError(
            "Lexicon parsing found zero hedging phrases — check hedging-lexicon.md's "
            "'## Hedging phrases' header and '### <category>' / '- phrase' structure."
        )
    if not confident:
        raise ValueError(
            "Lexicon parsing found zero confident phrases — check hedging-lexicon.md's "
            "'## Confident / unqualified phrases' header and structure."
        )

    return Lexicon(
        hedging=tuple(hedging),
        confident=tuple(confident),
        hedging_pattern=_build_alternation_pattern(tuple(hedging)),
        confident_pattern=_build_alternation_pattern(tuple(confident)),
    )


@lru_cache(maxsize=8)
def _load_lexicon_cached(path_str: str) -> Lexicon:
    text = Path(path_str).read_text(encoding="utf-8")
    return parse_lexicon(text)


def load_lexicon(path: str | Path = DEFAULT_LEXICON_PATH) -> Lexicon:
    """Load and parse the hedging lexicon from disk, caching by resolved path."""
    return _load_lexicon_cached(str(Path(path)))


def _find_matches(
    text: str, entries: tuple[LexiconEntry, ...], pattern: re.Pattern[str]
) -> tuple[PhraseMatch, ...]:
    if not entries:
        return ()
    category_by_phrase = {e.phrase: e.category for e in entries}
    matches: list[PhraseMatch] = []
    seen: set[str] = set()
    for m in pattern.finditer(text):
        matched = m.group(0).lower()
        if matched in seen:
            continue
        seen.add(matched)
        matches.append(PhraseMatch(phrase=matched, category=category_by_phrase.get(matched, "")))
    return tuple(matches)


def classify_sentence(text: str, lexicon: Optional[Lexicon] = None) -> HedgeClassification:
    """Classify a single sentence as hedged, confident, or unmarked.

    Hedge phrases take precedence: a sentence containing both a hedge and a
    confident marker (e.g. "We delivered strong growth, though results may
    vary going forward") is still HEDGED — the hedge qualifies the claim
    regardless of what else is in the sentence.
    """
    lexicon = lexicon or load_lexicon()
    hedge_matches = _find_matches(text, lexicon.hedging, lexicon.hedging_pattern)
    confident_matches = _find_matches(text, lexicon.confident, lexicon.confident_pattern)

    if hedge_matches:
        label = HEDGED
    elif confident_matches:
        label = CONFIDENT
    else:
        label = UNMARKED

    return HedgeClassification(
        text=text.strip(),
        label=label,
        hedge_matches=hedge_matches,
        confident_matches=confident_matches,
    )


def split_sentences(text: str) -> list[str]:
    """Split turn text into sentences. Deterministic, regex-based (see module docstring)."""
    text = text.strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def analyze_turn(turn_text: str, lexicon: Optional[Lexicon] = None) -> list[HedgeClassification]:
    """Classify every sentence in a transcript turn's text."""
    lexicon = lexicon or load_lexicon()
    return [classify_sentence(sentence, lexicon) for sentence in split_sentences(turn_text)]

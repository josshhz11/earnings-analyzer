"""Deterministic speaker-turn segmentation for earnings call transcripts.

No LLM calls — this is regex/rule-based parsing over the plain text produced by
`pdf_loader.load_pdf_text`. Per CLAUDE.md's deterministic-before-LLM principle,
speaker-change detection is pattern matching, not a model call.

## The formatting problem this solves

Earnings call transcript PDFs are not standardized. Two real vendor formats,
inspected directly to design these patterns (see `data/sample_transcripts/`):

- **"Standalone header" style** (e.g. Meta's IR-published transcripts): a speaker
  change is a short isolated line — "Mark Zuckerberg, CEO" — flanked by blank
  lines on both sides, with no colon. The paragraph of dialogue follows as a
  separate block.
- **"Inline colon" style** (e.g. Assurant's, and the Operator/Q&A turns in
  *both* samples): "Brian Nowak: Thanks for taking my questions..." — name
  (optionally ", Title") then a colon, with dialogue starting on the same line
  and continuing until the next such cue. Some transcripts (Assurant's Q&A)
  pack multiple turns back-to-back with *no* blank line between them — e.g.
  "Keith Demmings: Good morning, Mark. Keith Meier: Hey, Mark." on consecutive
  lines of the same paragraph block — so inline cues are matched line by line
  within a block, not just at each block's first line.

Both patterns are handled. Where neither pattern matches cleanly, or no Q&A
boundary can be located, this module flags `low_confidence=True` with an
explanatory entry in `warnings` rather than guessing — see KNOWN_ISSUES.md for
the specific formatting edge cases this does and doesn't handle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

PREPARED_REMARKS = "Prepared Remarks"
QA = "Q&A"

# A "name" is 1-5 capitalized words (letters, periods, apostrophes, hyphens
# within a word — e.g. "Jean-Pierre", "Susan Li", "J. Smith"). Bounding it to
# 5 words keeps this from greedily eating into a following sentence.
_NAME = r"[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4}"

# "Name: rest" or "Name, Title: rest" — the inline-colon cue style. Matched
# against a block's first line only.
INLINE_CUE_RE = re.compile(rf"^(?P<name>{_NAME})(?:,\s*(?P<title>[^:]+?))?:\s*(?P<rest>.*)$")

# "Name, Title" with no colon, on a line by itself — the standalone-header cue
# style. Only ever tested against a block that is exactly one line, so this
# alone can't misfire against a multi-line body paragraph; it can still
# misfire against a short one-line body paragraph that happens to start with a
# capitalized word + comma (documented as a known limitation).
STANDALONE_HEADER_RE = re.compile(rf"^(?P<name>{_NAME}),\s*(?P<title>[A-Za-z0-9&,.'/\-\s]+)$")

# Signals that an Operator turn is *the* prepared-remarks -> Q&A handoff, not
# just the call-opening welcome (which also often comes from "Operator").
QA_KEYWORDS_RE = re.compile(
    r"(?i)question.{0,20}(?:and|&).{0,20}answer"
    r"|open(?:ing)?(?: the| up)?(?: the)? (?:lines?|call|floor) for questions"
    r"|q\s*&\s*a\b"
)

# An explicit section heading line, e.g. "Question & Answer Section" — seen in
# the Assurant sample preceding the real Q&A-opening Operator turn.
QA_HEADING_RE = re.compile(
    r"(?i)^(question(?:s)?\s*(?:and|&)\s*answer(?:s)?(?:\s+section)?|q\s*&\s*a(?:\s+section)?)\s*:?\s*$"
)


@dataclass(frozen=True)
class Turn:
    """One speaker turn in a segmented transcript."""

    turn_number: int
    speaker_name: str
    speaker_title: Optional[str]
    section: str  # PREPARED_REMARKS or QA
    text: str


@dataclass(frozen=True)
class SegmentationResult:
    """Output of `segment_transcript`: the parsed turns plus a confidence signal."""

    turns: list[Turn]
    low_confidence: bool
    warnings: list[str]


@dataclass
class _DraftTurn:
    """Mutable turn-in-progress used while parsing; converted to `Turn` at the end."""

    turn_number: int
    speaker_name: str
    speaker_title: Optional[str]
    text_parts: list[str]


def _split_into_blocks(text: str) -> list[list[str]]:
    """Group non-blank lines into blocks separated by one-or-more blank lines.

    A block is the unit segmentation reasons about: either a single-line
    speaker cue, an inline-cue-plus-dialogue block, or a continuation
    paragraph belonging to the most recent turn.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if line:
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def segment_transcript(text: str) -> SegmentationResult:
    """Parse raw transcript text into speaker turns with section labels.

    Fully deterministic: no LLM calls. See module docstring for the two cue
    styles this recognizes and how the Prepared Remarks / Q&A boundary is
    located.
    """
    blocks = _split_into_blocks(text)

    drafts: list[_DraftTurn] = []
    warnings: list[str] = []
    qa_boundary_turn: Optional[int] = None
    pending_qa_heading = False

    orphan_lines: list[str] = []  # buffered front-matter lines seen before any turn exists

    def flush_orphans() -> None:
        if orphan_lines:
            preview = orphan_lines[0][:60]
            warnings.append(
                f"Skipped {len(orphan_lines)} line(s) of unattributed front matter "
                f"before any speaker cue was recognized: {preview!r}..."
            )
            orphan_lines.clear()

    for block in blocks:
        # The standalone "Name, Title" header style (no colon) only ever
        # applies to a block that is a single isolated line — that isolation
        # (blank lines on both sides) is exactly the signal that distinguishes
        # it from an ordinary short sentence. Multi-line blocks are always
        # scanned line by line below for inline ": "-style cues instead, since
        # some transcripts pack several inline-cue turns into one block with
        # no blank line between them (see module docstring).
        if len(block) == 1:
            line = block[0]
            if QA_HEADING_RE.match(line):
                pending_qa_heading = True
                continue
            standalone_match = STANDALONE_HEADER_RE.match(line)
            if standalone_match:
                flush_orphans()
                draft = _DraftTurn(
                    turn_number=len(drafts) + 1,
                    speaker_name=standalone_match.group("name").strip(),
                    speaker_title=standalone_match.group("title").strip(),
                    text_parts=[],
                )
                drafts.append(draft)
                if pending_qa_heading:
                    qa_boundary_turn = draft.turn_number
                    pending_qa_heading = False
                continue
            # Not a heading or a standalone header — fall through to the
            # line-level scan below (handles a single-line inline cue, or an
            # orphan/continuation line).

        for line in block:
            if QA_HEADING_RE.match(line):
                pending_qa_heading = True
                continue

            inline_match = INLINE_CUE_RE.match(line)
            if inline_match:
                flush_orphans()
                title = inline_match.group("title")
                draft = _DraftTurn(
                    turn_number=len(drafts) + 1,
                    speaker_name=inline_match.group("name").strip(),
                    speaker_title=title.strip() if title else None,
                    text_parts=[],
                )
                rest = inline_match.group("rest").strip()
                if rest:
                    draft.text_parts.append(rest)
                drafts.append(draft)
                if pending_qa_heading:
                    qa_boundary_turn = draft.turn_number
                    pending_qa_heading = False
            elif drafts:
                drafts[-1].text_parts.append(line)
            else:
                orphan_lines.append(line)

    flush_orphans()

    # Locate the Prepared Remarks -> Q&A boundary via an Operator turn whose
    # *full* assembled text (not just its cue line) carries a Q&A signal —
    # deferred to a post-pass since the keyword text often arrives on
    # continuation lines after the cue line itself (e.g. "Operator: " alone,
    # followed by "Thank you. We will now open the lines for..." on the next
    # line of the same block).
    if qa_boundary_turn is None:
        for d in drafts:
            if d.speaker_name.lower() == "operator" and QA_KEYWORDS_RE.search(" ".join(d.text_parts)):
                qa_boundary_turn = d.turn_number
                break

    # Fallback: no heading and no keyword-bearing Operator turn found, but the
    # Operator does appear at least twice — assume the second appearance is
    # the Q&A handoff (the first is very commonly just the call-opening
    # welcome). This is a weaker signal, so it's called out in warnings.
    if qa_boundary_turn is None:
        operator_turns = [d.turn_number for d in drafts if d.speaker_name.lower() == "operator"]
        if len(operator_turns) >= 2:
            qa_boundary_turn = operator_turns[1]
            warnings.append(
                "No explicit Q&A heading or keyword match found; used the second "
                "'Operator' turn as the Prepared Remarks -> Q&A boundary as a "
                "weaker fallback signal."
            )

    turns = [
        Turn(
            turn_number=d.turn_number,
            speaker_name=d.speaker_name,
            speaker_title=d.speaker_title,
            section=QA if qa_boundary_turn is not None and d.turn_number >= qa_boundary_turn
            else PREPARED_REMARKS,
            text=" ".join(d.text_parts).strip(),
        )
        for d in drafts
    ]

    low_confidence = False
    if qa_boundary_turn is None:
        warnings.append(
            "No Q&A section boundary could be located; the entire transcript "
            f"was labeled '{PREPARED_REMARKS}'."
        )
        low_confidence = True
    if len(turns) < 2:
        warnings.append(
            f"Only {len(turns)} turn(s) were parsed — the speaker-cue patterns "
            "likely did not match this transcript's formatting."
        )
        low_confidence = True

    return SegmentationResult(turns=turns, low_confidence=low_confidence, warnings=warnings)

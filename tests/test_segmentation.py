"""Tests for src.ingestion.segmentation — deterministic speaker-turn parsing.

Exercises both real sample transcripts (two different vendor formatting
styles — see the segmentation module docstring) plus synthetic transcripts
designed to hit the low-confidence fallback paths deliberately.
"""

from pathlib import Path

from src.ingestion.pdf_loader import load_pdf_text
from src.ingestion.segmentation import PREPARED_REMARKS, QA, segment_transcript

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_transcripts"
META_PDF = SAMPLE_DIR / "META-Q4-2024-Earnings-Call-Transcript.pdf"
ASSURANT_PDF = SAMPLE_DIR / "Assurant-Q325-Earnings-Call-Transcript.pdf"


def _boundary_turn_number(turns):
    """Return the turn_number of the first Q&A turn, or None if there isn't one."""
    for turn in turns:
        if turn.section == QA:
            return turn.turn_number
    return None


# --- Real transcript: Meta (standalone "Name, Title" header style) --------


def test_meta_transcript_segments_with_high_confidence():
    doc = load_pdf_text(META_PDF)
    result = segment_transcript(doc.text)

    assert result.low_confidence is False
    assert len(result.turns) >= 30  # regression floor; exact count is 35 as of writing

    boundary = _boundary_turn_number(result.turns)
    assert boundary is not None

    # Every turn is entirely on one side of the boundary or the other, in order.
    for turn in result.turns:
        expected = PREPARED_REMARKS if turn.turn_number < boundary else QA
        assert turn.section == expected

    assert all(turn.text for turn in result.turns), "no turn should have empty text"


def test_meta_transcript_known_speakers_and_titles():
    doc = load_pdf_text(META_PDF)
    result = segment_transcript(doc.text)
    turns = result.turns

    assert turns[0].speaker_name == "Kenneth Dorell"
    assert turns[0].speaker_title == "Director, Investor Relations"
    assert turns[0].section == PREPARED_REMARKS

    assert turns[1].speaker_name == "Mark Zuckerberg"
    assert turns[1].speaker_title == "CEO"

    assert turns[2].speaker_name == "Susan Li"
    assert turns[2].speaker_title == "CFO"

    # The Q&A-opening turn is the Operator, detected via the "question and
    # answer session" keyword phrase in its own text (no explicit heading in
    # this transcript).
    boundary = _boundary_turn_number(turns)
    boundary_turn = next(t for t in turns if t.turn_number == boundary)
    assert boundary_turn.speaker_name == "Operator"

    analyst_turns = [t for t in turns if t.speaker_name == "Brian Nowak"]
    assert analyst_turns, "expected at least one turn from analyst Brian Nowak"
    assert analyst_turns[0].section == QA


# --- Real transcript: Assurant (dense inline-colon style, no blank lines --
# --- between consecutive Q&A turns) ---------------------------------------


def test_assurant_transcript_segments_with_high_confidence():
    doc = load_pdf_text(ASSURANT_PDF)
    result = segment_transcript(doc.text)

    assert result.low_confidence is False
    # Dense Q&A format packs many short turns per block; regression floor.
    assert len(result.turns) >= 60  # exact count is 70 as of writing

    boundary = _boundary_turn_number(result.turns)
    assert boundary is not None
    for turn in result.turns:
        expected = PREPARED_REMARKS if turn.turn_number < boundary else QA
        assert turn.section == expected


def test_assurant_transcript_dense_qa_turns_are_split_correctly():
    """Regression test for the bug where multiple inline-cue turns packed into
    one block (no blank line between them) were incorrectly merged into a
    single turn — see DECISIONS.md / KNOWN_ISSUES.md.
    """
    doc = load_pdf_text(ASSURANT_PDF)
    result = segment_transcript(doc.text)
    turns = result.turns

    # Back-to-back one-line exchanges right after the Q&A-opening Operator
    # turn: "Keith Demmings: Good morning, Mark." then "Keith Meier: Hey,
    # Mark." on consecutive lines with no blank line between them. (Keith
    # Demmings also speaks during Prepared Remarks, so search within Q&A only.)
    demmings_idx = next(i for i, t in enumerate(turns) if t.speaker_name == "Keith Demmings" and t.section == QA)
    assert turns[demmings_idx + 1].speaker_name == "Keith Meier"
    assert turns[demmings_idx].text == "Good morning, Mark."
    assert turns[demmings_idx + 1].text == "Hey, Mark."

    # An analyst who asks multiple questions across the same Operator segment
    # should appear as several distinct Q&A turns, not one merged blob.
    mark_hughes_turns = [t for t in turns if t.speaker_name == "Mark Hughes"]
    assert len(mark_hughes_turns) >= 3
    assert all(t.section == QA for t in mark_hughes_turns)


# --- Synthetic edge cases: low-confidence fallback paths -------------------


def test_no_recognizable_speaker_cues_is_low_confidence():
    text = (
        "This is a plain block of prose with no speaker cues at all.\n"
        "It just keeps going across multiple lines like a regular paragraph\n"
        "would, with nothing that looks like 'Name: text' or 'Name, Title'.\n"
    )
    result = segment_transcript(text)

    assert result.low_confidence is True
    assert len(result.turns) == 0
    assert any("front matter" in w for w in result.warnings)


def test_missing_qa_boundary_is_low_confidence():
    """Speaker cues are recognized fine, but there's no Operator turn and no
    Q&A heading anywhere — segmentation should still succeed but flag that it
    couldn't find the Prepared Remarks -> Q&A boundary, rather than guessing.
    """
    text = (
        "Jane Doe, CEO\n"
        "\n"
        "Thanks everyone for joining today's call.\n"
        "\n"
        "John Smith, CFO\n"
        "\n"
        "Revenue was up 10% year over year.\n"
    )
    result = segment_transcript(text)

    assert result.low_confidence is True
    assert len(result.turns) == 2
    assert all(t.section == PREPARED_REMARKS for t in result.turns)
    assert any("Q&A section boundary" in w for w in result.warnings)


def test_single_operator_mention_without_qa_keywords_is_low_confidence():
    """Only one Operator turn exists and it doesn't contain Q&A-transition
    language — the weaker "second Operator turn" fallback can't apply, and the
    keyword-search tier finds nothing either, so this should stay low
    confidence rather than guess a boundary.
    """
    text = (
        "Jane Doe, CEO\n"
        "\n"
        "Thanks everyone for joining.\n"
        "\n"
        "Operator:\n"
        "Please stand by while we connect the call.\n"
    )
    result = segment_transcript(text)

    assert result.low_confidence is True
    assert all(t.section == PREPARED_REMARKS for t in result.turns)


def test_explicit_qa_heading_sets_boundary():
    text = (
        "Jane Doe, CEO\n"
        "\n"
        "Thanks everyone for joining today's call.\n"
        "\n"
        "Question & Answer Section\n"
        "\n"
        "Operator: We will now begin the call.\n"
        "\n"
        "Analyst One: What's your outlook for next quarter?\n"
    )
    result = segment_transcript(text)

    assert result.low_confidence is False
    assert len(result.turns) == 3
    assert result.turns[0].section == PREPARED_REMARKS
    assert result.turns[1].section == QA
    assert result.turns[1].speaker_name == "Operator"
    assert result.turns[2].section == QA


def test_front_matter_before_first_cue_is_skipped_not_attributed():
    text = (
        "COMPANY NAME\n"
        "Q3 2025 Earnings Call Transcript\n"
        "\n"
        "PARTICIPANTS\n"
        "Jane Doe - CEO\n"
        "John Smith - CFO\n"
        "\n"
        "Jane Doe, CEO\n"
        "\n"
        "Thanks everyone for joining today's call.\n"
    )
    result = segment_transcript(text)

    assert len(result.turns) == 1
    assert result.turns[0].speaker_name == "Jane Doe"
    assert "front matter" in result.warnings[0]

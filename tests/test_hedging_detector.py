"""Tests for src.analysis.hedging_detector — deterministic hedging/tone detection.

Hand-written example sentences with known expected classifications, plus tests
for the lexicon parser itself (structure, error handling) and sentence splitting.
"""

import pytest

from src.analysis.hedging_detector import (
    CONFIDENT,
    HEDGED,
    UNMARKED,
    analyze_turn,
    classify_sentence,
    load_lexicon,
    parse_lexicon,
    split_sentences,
)

# --- Lexicon loading/parsing -----------------------------------------------


def test_default_lexicon_loads_with_both_buckets_populated():
    lexicon = load_lexicon()
    assert len(lexicon.hedging) > 10
    assert len(lexicon.confident) > 10
    # Every category should be a non-empty string, not just an artifact of parsing.
    assert all(e.category for e in lexicon.hedging)
    assert all(e.category for e in lexicon.confident)


def test_parse_lexicon_rejects_missing_hedging_bucket():
    malformed = "## Confident / unqualified phrases\n### Some category\n- will\n"
    with pytest.raises(ValueError, match="hedging phrases"):
        parse_lexicon(malformed)


def test_parse_lexicon_rejects_missing_confident_bucket():
    malformed = "## Hedging phrases\n### Some category\n- may\n"
    with pytest.raises(ValueError, match="confident phrases"):
        parse_lexicon(malformed)


def test_parse_lexicon_ignores_bullets_outside_a_category():
    # A bullet before any "###" category header shouldn't be picked up.
    text = (
        "## Hedging phrases\n"
        "- orphan bullet, no category yet\n"
        "### Modal verbs\n"
        "- may\n"
        "## Confident / unqualified phrases\n"
        "### Strong verbs\n"
        "- will\n"
    )
    lexicon = parse_lexicon(text)
    assert [e.phrase for e in lexicon.hedging] == ["may"]
    assert [e.phrase for e in lexicon.confident] == ["will"]


# --- Sentence classification: hand-written examples with known labels ------


@pytest.mark.parametrize(
    "sentence,expected_label",
    [
        ("We expect revenue to grow in the low double digits next year.", HEDGED),
        ("Revenue grew 21 percent year over year.", CONFIDENT),
        ("The weather was nice today.", UNMARKED),
        ("We are confident that margins will expand.", CONFIDENT),
        ("Q4 total expenses were approximately 25 billion dollars.", HEDGED),
        ("Our guidance is subject to change based on market conditions.", HEDGED),
        ("We will deliver strong growth next year.", CONFIDENT),
        ("It is possible that demand slows in the second half.", HEDGED),
        ("We delivered record revenue this quarter.", CONFIDENT),
        ("These are forward-looking statements.", HEDGED),
    ],
)
def test_classify_sentence_known_examples(sentence, expected_label):
    result = classify_sentence(sentence)
    assert result.label == expected_label


def test_hedge_takes_precedence_over_confident_markers():
    """A sentence with both a hedge and a confident marker should still be
    HEDGED — the hedge qualifies the whole statement (see docstring)."""
    sentence = "We believe this trend will continue, though results may vary by region."
    result = classify_sentence(sentence)
    assert result.label == HEDGED
    assert {m.phrase for m in result.hedge_matches} == {"we believe", "may"}
    assert {m.phrase for m in result.confident_matches} == {"will"}


def test_classification_is_case_insensitive():
    result = classify_sentence("WE BELIEVE this will work out fine.")
    assert result.label == HEDGED
    assert result.hedge_matches[0].phrase == "we believe"


def test_no_false_positive_on_substring_of_a_longer_word():
    """'may' must not match inside 'Mayfield' — word-boundary matching, not substring."""
    result = classify_sentence("Mayfield Incorporated reported strong results.")
    assert result.label == CONFIDENT
    assert result.hedge_matches == ()
    assert result.confident_matches[0].phrase == "reported"


def test_phrase_matches_carry_their_lexicon_category():
    result = classify_sentence("Our results may fluctuate depending on market conditions.")
    assert result.label == HEDGED
    category_by_phrase = {m.phrase: m.category for m in result.hedge_matches}
    assert "Modal" in category_by_phrase["may"]
    assert "Uncertainty" in category_by_phrase["fluctuate"]
    assert "Uncertainty" in category_by_phrase["depending on"]


# --- Sentence splitting -----------------------------------------------------


def test_split_sentences_basic():
    text = "We expect growth. Revenue was strong. Margins may compress."
    assert split_sentences(text) == [
        "We expect growth.",
        "Revenue was strong.",
        "Margins may compress.",
    ]


def test_split_sentences_empty_string():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


# --- Turn-level analysis ----------------------------------------------------


def test_analyze_turn_classifies_each_sentence_independently():
    turn_text = (
        "Thanks Mark and good afternoon everyone. Q4 total revenue increased to $48.4 "
        "billion, up 21 percent. We expect this momentum to continue into next year."
    )
    results = analyze_turn(turn_text)
    assert len(results) == 3
    assert results[0].label == UNMARKED
    assert results[1].label == CONFIDENT
    assert results[2].label == HEDGED


def test_analyze_turn_empty_text_returns_empty_list():
    assert analyze_turn("") == []

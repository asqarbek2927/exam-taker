import pytest

from apps.questions.choices import QuestionType
from apps.questions.validators import validate_options


def opts(*pairs):
    return [{"text": text, "is_correct": correct} for text, correct in pairs]


@pytest.mark.parametrize(
    ("question_type", "options"),
    [
        (QuestionType.SINGLE_CHOICE, opts(("A", True), ("B", False))),
        (QuestionType.SINGLE_CHOICE, opts(("A", True), ("B", False), ("C", False), ("D", False))),
        (QuestionType.MULTIPLE_CHOICE, opts(("A", True), ("B", False))),
        (QuestionType.MULTIPLE_CHOICE, opts(("A", True), ("B", True), ("C", True))),
        (QuestionType.TRUE_FALSE, opts(("True", True), ("False", False))),
        (QuestionType.OPEN_ENDED, []),
    ],
)
def test_valid_combinations(question_type, options):
    assert validate_options(question_type, options) == []


@pytest.mark.parametrize(
    ("question_type", "options"),
    [
        (QuestionType.SINGLE_CHOICE, opts(("A", True))),  # 1 ta option
        (QuestionType.SINGLE_CHOICE, opts(("A", True), ("B", True))),  # 2 ta to‘g‘ri
        (QuestionType.SINGLE_CHOICE, opts(("A", False), ("B", False))),  # to‘g‘ri yo‘q
        (QuestionType.MULTIPLE_CHOICE, opts(("A", False), ("B", False))),  # to‘g‘ri yo‘q
        (QuestionType.MULTIPLE_CHOICE, opts(("A", True))),  # 1 ta option
        (QuestionType.TRUE_FALSE, opts(("T", True), ("F", False), ("?", False))),
        (QuestionType.TRUE_FALSE, opts(("T", True), ("F", True))),
        (QuestionType.TRUE_FALSE, opts(("T", False), ("F", False))),
        (QuestionType.OPEN_ENDED, opts(("A", True))),
        (QuestionType.SINGLE_CHOICE, opts(("A", True), ("a ", False))),  # takror (case-insens.)
        (QuestionType.SINGLE_CHOICE, opts(("A", True), ("  ", False))),  # bo‘sh matn
        ("UNKNOWN", opts(("A", True), ("B", False))),
    ],
)
def test_invalid_combinations(question_type, options):
    assert validate_options(question_type, options)

from decimal import Decimal

import pytest

from apps.attempts.choices import AttemptStatus
from apps.attempts.grading import grade_choice_answer, money, passed, percentage
from apps.attempts.models import StudentAnswer
from apps.attempts.services import recalculate_attempt
from apps.attempts.tests.factories import AttemptFactory
from apps.exams.tests.factories import ExamFactory, ExamQuestionFactory
from apps.questions.choices import QuestionType

D = Decimal


@pytest.mark.parametrize(
    ("qtype", "points", "correct", "selected", "expected"),
    [
        # SINGLE / TRUE_FALSE: hammasi yoki hech narsa
        (QuestionType.SINGLE_CHOICE, D("2"), {"a"}, {"a"}, (True, D("2.00"))),
        (QuestionType.SINGLE_CHOICE, D("2"), {"a"}, {"b"}, (False, D("0.00"))),
        (QuestionType.SINGLE_CHOICE, D("2"), {"a"}, set(), (False, D("0.00"))),
        (QuestionType.SINGLE_CHOICE, D("2"), {"a"}, {"a", "b"}, (False, D("0.00"))),
        (QuestionType.TRUE_FALSE, D("1"), {"t"}, {"t"}, (True, D("1.00"))),
        (QuestionType.TRUE_FALSE, D("1"), {"t"}, {"f"}, (False, D("0.00"))),
        # MULTIPLE: (to‘g‘ri − noto‘g‘ri) / jami to‘g‘ri, [0, 1] oralig‘ida
        (QuestionType.MULTIPLE_CHOICE, D("3"), {"a", "b"}, {"a", "b"}, (True, D("3.00"))),
        (QuestionType.MULTIPLE_CHOICE, D("3"), {"a", "b"}, {"a"}, (False, D("1.50"))),
        (QuestionType.MULTIPLE_CHOICE, D("3"), {"a", "b"}, {"a", "w"}, (False, D("0.00"))),
        (QuestionType.MULTIPLE_CHOICE, D("3"), {"a", "b"}, {"w"}, (False, D("0.00"))),
        (QuestionType.MULTIPLE_CHOICE, D("3"), {"a", "b"}, {"a", "b", "w"}, (False, D("0.00"))),
        (QuestionType.MULTIPLE_CHOICE, D("3"), {"a", "b"}, set(), (False, D("0.00"))),
        (QuestionType.MULTIPLE_CHOICE, D("1"), {"a", "b", "c"}, {"a"}, (False, D("0.33"))),
        (QuestionType.MULTIPLE_CHOICE, D("1"), {"a", "b", "c"}, {"a", "b"}, (False, D("0.67"))),
    ],
)
def test_grade_choice_answer(qtype, points, correct, selected, expected):
    assert grade_choice_answer(qtype, points, correct, selected) == expected


def test_selecting_every_option_never_gives_full_marks():
    options = {"a", "b", "c", "d"}
    _, points = grade_choice_answer(QuestionType.MULTIPLE_CHOICE, D("4"), {"a"}, options)
    assert points < D("4")


def test_money_rounds_half_up():
    assert money(D("0.125")) == D("0.13")
    assert money(D("0.124")) == D("0.12")


def test_percentage_and_passed_use_exact_comparison():
    assert percentage(D("1"), D("3")) == D("33.33")
    assert passed(D("1"), D("3"), D("33.33")) is True  # 33.333… >= 33.33
    assert passed(D("1"), D("3"), D("33.34")) is False
    assert passed(D("5"), D("10"), D("50")) is True  # aynan chegarada o‘tadi
    assert passed(D("4.99"), D("10"), D("50")) is False
    assert passed(D("0"), D("10"), D("0")) is True


@pytest.mark.django_db
def test_recalculate_attempt_waits_for_manual_grading():
    exam = ExamFactory(passing_score_percent=50)
    ExamQuestionFactory(exam=exam, points=6)
    open_question = ExamQuestionFactory(exam=exam, points=4)
    attempt = AttemptFactory(assignment__exam=exam, assignment__ensure_question=False)
    first, second = (
        attempt.assignment.exam.exam_questions.order_by("points")[::-1][0],
        open_question,
    )
    StudentAnswer.objects.create(attempt=attempt, exam_question=first, points_awarded=D("6"))
    pending = StudentAnswer.objects.create(
        attempt=attempt, exam_question=second, text_answer="essay"
    )

    recalculate_attempt(attempt)
    attempt.refresh_from_db()
    assert attempt.status == AttemptStatus.PENDING_GRADING
    assert (attempt.score, attempt.percentage, attempt.passed) == (None, None, None)

    pending.points_awarded = D("1")  # keyingi bosqichdagi qo‘lda baholash shu yerga keladi
    pending.save()
    recalculate_attempt(attempt)
    attempt.refresh_from_db()
    assert attempt.status == AttemptStatus.GRADED
    assert attempt.score == D("7.00")
    assert attempt.percentage == D("70.00")
    assert attempt.passed is True

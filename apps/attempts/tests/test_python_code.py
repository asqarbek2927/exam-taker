"""PYTHON_CODE savoli: saqlash, topshirish va qo‘lda baholash (frontend integration check)."""

from decimal import Decimal

import pytest

from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    ModuleFactory,
)
from apps.assignments.tests.factories import AssignmentFactory
from apps.attempts.choices import AttemptStatus
from apps.attempts.models import StudentAnswer
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory, ExamQuestionFactory
from apps.questions.choices import QuestionType
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

CODE = "def f(x):\n    return x + 3\n\n\tprint(f(2))  \n"


@pytest.fixture
def python_world():
    course = CourseFactory()
    teacher = TeacherFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    student = StudentFactory()
    EnrollmentFactory(course=course, student=student)
    module = ModuleFactory(course=course)
    exam = ExamFactory(
        course=course, created_by=teacher, status=ExamStatus.READY, passing_score_percent=50
    )
    question = QuestionFactory(
        course=course,
        module=module,
        created_by=teacher,
        type=QuestionType.PYTHON_CODE,
        text="Write Python that prints 5",
        options=[],
    )
    exam_question = ExamQuestionFactory(exam=exam, question=question, points=5, position=1)
    assignment = AssignmentFactory(
        exam=exam,
        ensure_question=False,
        published_by=teacher,
        result_review_mode="AFTER_GRADING",
    )
    return teacher, student, question, exam_question, assignment


def _python_entry(body):
    (entry,) = body["questions"]
    return entry


def test_python_code_full_flow(auth_client, python_world):
    teacher, student, question, exam_question, assignment = python_world
    client = auth_client(student)

    started = client.post(f"/api/v1/exam-assignments/{assignment.id}/start")
    assert started.status_code in (200, 201), started.json()
    attempt_id = started.json()["id"]
    entry = _python_entry(started.json())
    assert entry["type"] == "PYTHON_CODE"
    assert entry["options"] == []
    assert entry["answer"] is None

    # Bankdagi savol keyin tahrirlansa ham attempt snapshot o‘zgarmaydi.
    question.text = "Edited later"
    question.save(update_fields=["text"])

    url = f"/api/v1/attempts/{attempt_id}/answers/{exam_question.id}"
    saved = client.put(url, {"text_answer": CODE, "revision": 0}, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["text_answer"] == CODE
    assert saved.json()["option_ids"] == []

    # option_ids Python savoliga yuborilmaydi.
    bad = client.put(
        url,
        {"option_ids": [str(exam_question.id)], "revision": saved.json()["revision"]},
        format="json",
    )
    assert bad.status_code >= 400

    # Reload: aniq kod va revision qaytadi.
    reloaded = _python_entry(client.get(f"/api/v1/attempts/{attempt_id}").json())
    assert reloaded["text"] == "Write Python that prints 5"
    assert reloaded["answer"]["text_answer"] == CODE
    assert reloaded["answer"]["revision"] == saved.json()["revision"]

    submitted = client.post(f"/api/v1/attempts/{attempt_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == AttemptStatus.PENDING_GRADING
    assert submitted.json()["score"] is None
    assert submitted.json()["passed"] is None

    staff = auth_client(teacher)
    pending = staff.get("/api/v1/grading/pending").json()["data"]
    assert [row["id"] for row in pending] == [attempt_id]
    staff_detail = staff.get(f"/api/v1/attempts/{attempt_id}").json()
    (staff_answer,) = staff_detail["answers"]
    assert staff_answer["question"]["type"] == "PYTHON_CODE"
    assert staff_answer["text_answer"] == CODE
    assert Decimal(str(staff_answer["max_points"])) == Decimal("5")

    answer = StudentAnswer.objects.get(attempt_id=attempt_id)
    assert answer.points_awarded is None
    grade_url = f"/api/v1/answers/{answer.id}/grade"
    too_many = staff.patch(grade_url, {"points_awarded": 6}, format="json")
    assert too_many.status_code == 400
    other_teacher = auth_client(TeacherFactory())
    assert other_teacher.patch(grade_url, {"points_awarded": 3}, format="json").status_code == 404

    graded = staff.patch(
        grade_url, {"points_awarded": 3, "teacher_feedback": "Correct"}, format="json"
    )
    assert graded.status_code == 200, graded.json()
    assert graded.json()["attempt"]["status"] == AttemptStatus.GRADED
    assert Decimal(str(graded.json()["attempt"]["score"])) == Decimal("3")
    assert graded.json()["attempt"]["passed"] is True


def test_empty_python_answer_is_unanswered_and_scores_zero(auth_client, python_world):
    _, student, _, exam_question, assignment = python_world
    client = auth_client(student)
    attempt_id = client.post(f"/api/v1/exam-assignments/{assignment.id}/start").json()["id"]
    url = f"/api/v1/attempts/{attempt_id}/answers/{exam_question.id}"
    assert client.put(url, {"text_answer": "", "revision": 0}, format="json").status_code == 200

    submitted = client.post(f"/api/v1/attempts/{attempt_id}/submit").json()
    assert submitted["status"] == AttemptStatus.GRADED
    answer = StudentAnswer.objects.get(attempt_id=attempt_id)
    assert answer.points_awarded == Decimal("0.00")
    assert answer.is_correct is False


def test_python_answer_accepts_up_to_20000_characters(auth_client, python_world):
    _, student, _, exam_question, assignment = python_world
    client = auth_client(student)
    attempt_id = client.post(f"/api/v1/exam-assignments/{assignment.id}/start").json()["id"]
    url = f"/api/v1/attempts/{attempt_id}/answers/{exam_question.id}"
    ok = client.put(url, {"text_answer": "x" * 20000, "revision": 0}, format="json")
    assert ok.status_code == 200
    too_long = client.put(
        url, {"text_answer": "x" * 20001, "revision": ok.json()["revision"]}, format="json"
    )
    assert too_long.status_code == 422

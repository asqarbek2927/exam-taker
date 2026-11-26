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


# --------------------------------------------------------------------------
# Frontend handoff "Integration check" — faqat API orqali, factory'siz oqim.
# --------------------------------------------------------------------------
def _iso(delta):
    from django.utils import timezone

    return (timezone.now() + delta).isoformat()


def _api_world(auth_client, *, review_mode):
    from datetime import timedelta

    course = CourseFactory()
    teacher = TeacherFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    student = StudentFactory()
    EnrollmentFactory(course=course, student=student)
    module = ModuleFactory(course=course)
    staff = auth_client(teacher)

    created = staff.post(
        "/api/v1/questions",
        {
            "course_id": str(course.id),
            "module_id": str(module.id),
            "type": "PYTHON_CODE",
            "difficulty": "MEDIUM",
            "text": "Write Python that prints 5",
            "default_points": 5,
            "options": [],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert created.json()["type"] == "PYTHON_CODE"
    question_id = created.json()["id"]

    exam = staff.post(
        "/api/v1/exams",
        {
            "course_id": str(course.id),
            "title": "Python exam",
            "passing_score_percent": 50,
            "status": "READY",
            "module_ids": [str(module.id)],
            "questions": [{"question_id": question_id}],
        },
        format="json",
    )
    assert exam.status_code == 201, exam.json()
    (exam_question,) = exam.json()["questions"]
    assert exam_question["question"]["type"] == "PYTHON_CODE"

    assignment = staff.post(
        "/api/v1/exam-assignments",
        {
            "exam_id": exam.json()["id"],
            "audience_type": "ALL_COURSE_STUDENTS",
            "start_at": _iso(timedelta(hours=-1)),
            "end_at": _iso(timedelta(days=1)),
            "duration_minutes": 30,
            "max_attempts": 1,
            "result_review_mode": review_mode,
        },
        format="json",
    )
    assert assignment.status_code == 201, assignment.json()
    return {
        "staff": staff,
        "student": auth_client(student),
        "question_id": question_id,
        "exam_question_id": exam_question["id"],
        "assignment_id": assignment.json()["id"],
    }


def _take_and_grade(world, code=CODE):
    student = world["student"]
    started = student.post(f"/api/v1/exam-assignments/{world['assignment_id']}/start")
    assert started.status_code == 201, started.json()
    attempt_id = started.json()["id"]

    # Savol bankda keyin tahrirlansa ham faol attempt o‘zgarmaydi (snapshot).
    world["staff"].patch(
        f"/api/v1/questions/{world['question_id']}", {"text": "Edited"}, format="json"
    )

    url = f"/api/v1/attempts/{attempt_id}/answers/{world['exam_question_id']}"
    saved = student.put(url, {"text_answer": code, "revision": 0}, format="json")
    assert saved.status_code == 200, saved.json()
    reloaded = _python_entry(student.get(f"/api/v1/attempts/{attempt_id}").json())
    assert reloaded["text"] == "Write Python that prints 5"
    assert reloaded["answer"] == {
        "option_ids": [],
        "text_answer": code,
        "revision": saved.json()["revision"],
    }

    submitted = student.post(f"/api/v1/attempts/{attempt_id}/submit").json()
    assert submitted["status"] == AttemptStatus.PENDING_GRADING
    assert submitted["score"] is None and submitted["passed"] is None
    # Natija baholanmaguncha studentning boshqa endpointlarida ham yashirin.
    (listed,) = student.get("/api/v1/attempts").json()["data"]
    assert listed["score"] is None and listed["percentage"] is None

    answer = StudentAnswer.objects.get(attempt_id=attempt_id)
    graded = world["staff"].patch(
        f"/api/v1/answers/{answer.id}/grade",
        {"points_awarded": 4, "teacher_feedback": "Correct"},
        format="json",
    )
    assert graded.status_code == 200, graded.json()
    return attempt_id, student.get(f"/api/v1/attempts/{attempt_id}").json()


def test_handoff_integration_after_grading_shows_own_code_and_feedback(auth_client):
    world = _api_world(auth_client, review_mode="AFTER_GRADING")
    _, result = _take_and_grade(world)

    assert result["status"] == AttemptStatus.GRADED
    assert Decimal(str(result["score"])) == Decimal("4")
    (answer,) = result["answers"]
    assert answer["question"]["type"] == "PYTHON_CODE"
    assert answer["text_answer"] == CODE
    assert answer["teacher_feedback"] == "Correct"
    assert "is_correct" not in answer
    assert "graded_by" not in answer  # staff-only maydon


def test_handoff_integration_score_only_hides_code_and_feedback(auth_client):
    world = _api_world(auth_client, review_mode="SCORE_ONLY")
    _, result = _take_and_grade(world)

    assert result["status"] == AttemptStatus.GRADED
    assert Decimal(str(result["score"])) == Decimal("4")
    assert "answers" not in result


def test_other_student_cannot_see_python_attempt(auth_client):
    world = _api_world(auth_client, review_mode="AFTER_GRADING")
    attempt_id, _ = _take_and_grade(world)
    outsider = auth_client(StudentFactory())
    assert outsider.get(f"/api/v1/attempts/{attempt_id}").status_code == 404


def test_python_question_rejects_choice_options_on_update(auth_client):
    world = _api_world(auth_client, review_mode="AFTER_GRADING")
    response = world["staff"].patch(
        f"/api/v1/questions/{world['question_id']}",
        {"options": [{"text": "a", "is_correct": True}, {"text": "b", "is_correct": False}]},
        format="json",
    )
    assert response.status_code >= 400


def test_crlf_and_unicode_code_is_stored_exactly(auth_client):
    code = "s = 'Salom, dunyo — ✓'\r\nif s:\r\n\tprint(s)   \r\n"
    world = _api_world(auth_client, review_mode="AFTER_GRADING")
    _, result = _take_and_grade(world, code=code)
    assert result["answers"][0]["text_answer"] == code

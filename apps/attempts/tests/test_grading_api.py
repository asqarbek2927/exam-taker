from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.academics.tests.factories import (
    CourseTeacherFactory,
    GroupStudentFactory,
    StudyGroupFactory,
)
from apps.assignments.tests.factories import AssignmentFactory
from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt, StudentAnswer
from apps.attempts.tests.conftest import option_id
from apps.audit.choices import AuditAction
from apps.audit.models import AuditLog
from apps.exams.tests.factories import ExamQuestionFactory
from apps.questions.choices import QuestionType
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

PENDING = "/api/v1/grading/pending"


def grade_url(answer):
    return f"/api/v1/answers/{answer.id}/grade"


@pytest.fixture
def submitted(api, world):
    """Student topshirgan, open-ended matni bor -> PENDING_GRADING attempt."""
    client = api(world.student)
    attempt_id = client.start(world.assignment).json()["id"]
    q = world.q
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(q["single"], "Right")])
    client.answer(
        attempt_id,
        world.eq["multi"],
        option_ids=[option_id(q["multi"], "R1"), option_id(q["multi"], "R2")],
    )
    client.answer(attempt_id, world.eq["tf"], option_ids=[option_id(q["tf"], "True")])
    client.answer(attempt_id, world.eq["open"], text_answer="My essay")
    client.submit(attempt_id)
    attempt = ExamAttempt.objects.get(pk=attempt_id)
    assert attempt.status == AttemptStatus.PENDING_GRADING
    return attempt


def open_answer(attempt, world):
    return StudentAnswer.objects.get(
        attempt=attempt,
        attempt_question__snapshot_question__source_exam_question_id=world.eq["open"].id,
    )


# ------------------------------- pending list -------------------------------
def test_pending_list_shows_attempts_to_grade(auth_client, admin, world, submitted):
    for user in (world.teacher, admin):
        body = auth_client(user).get(PENDING).json()
        assert [a["id"] for a in body["data"]] == [str(submitted.id)]
    row = auth_client(world.teacher).get(PENDING).json()["data"][0]
    assert row["pending_answers_count"] == 1
    assert row["student"]["id"] == str(world.student.id)
    assert row["status"] == "PENDING_GRADING"


def test_pending_list_excludes_other_statuses(auth_client, world, submitted):
    ExamAttempt.objects.create(
        assignment=world.assignment,
        student=StudentFactory(),
        attempt_number=1,
        started_at=timezone.now(),
        deadline_at=timezone.now() + timedelta(minutes=5),
    )  # IN_PROGRESS
    ExamAttempt.objects.create(
        assignment=world.assignment,
        student=StudentFactory(),
        attempt_number=1,
        started_at=timezone.now(),
        deadline_at=timezone.now(),
        status=AttemptStatus.GRADED,
    )
    ids = [a["id"] for a in auth_client(world.teacher).get(PENDING).json()["data"]]
    assert ids == [str(submitted.id)]


def test_pending_list_access_rules(auth_client, api_client, world, submitted):
    assert auth_client(world.student).get(PENDING).status_code == 403
    assert api_client.get(PENDING).status_code == 401
    outsider = TeacherFactory()  # boshqa kurs teacheri
    CourseTeacherFactory(teacher=outsider)
    assert auth_client(outsider).get(PENDING).json()["data"] == []


def test_pending_list_filters_and_ordering(auth_client, world, submitted, make_world):
    other = make_world()
    newer = ExamAttempt.objects.create(
        assignment=world.assignment,
        student=StudentFactory(),
        attempt_number=1,
        started_at=timezone.now(),
        deadline_at=timezone.now(),
        submitted_at=timezone.now() + timedelta(minutes=1),
        status=AttemptStatus.PENDING_GRADING,
    )
    group = StudyGroupFactory(course=world.course)
    GroupStudentFactory(group=group, student=world.student)
    client = auth_client(world.teacher)

    def ids(**params):
        return [a["id"] for a in client.get(PENDING, params).json()["data"]]

    assert ids() == [str(submitted.id), str(newer.id)]  # eng eskisi birinchi
    assert ids(course_id=world.course.id) == [str(submitted.id), str(newer.id)]
    assert ids(course_id=other.course.id) == []
    assert ids(exam_id=world.exam.id) == [str(submitted.id), str(newer.id)]
    assert ids(assignment_id=world.assignment.id) == [str(submitted.id), str(newer.id)]
    assert ids(student_id=world.student.id) == [str(submitted.id)]
    assert ids(group_id=group.id) == [str(submitted.id)]


def test_pending_list_finalizes_expired_attempts_first(auth_client, api, world):
    client = api(world.student)
    attempt_id = client.start(world.assignment).json()["id"]
    client.answer(attempt_id, world.eq["open"], text_answer="written in time")
    ExamAttempt.objects.filter(pk=attempt_id).update(
        deadline_at=timezone.now() - timedelta(minutes=5)
    )
    ids = [a["id"] for a in auth_client(world.teacher).get(PENDING).json()["data"]]
    assert ids == [attempt_id]


# ------------------------------- grade -------------------------------
def test_grading_the_only_open_answer_completes_the_attempt(auth_client, world, submitted):
    answer = open_answer(submitted, world)
    response = auth_client(world.teacher).patch(
        grade_url(answer),
        {"points_awarded": 3.5, "teacher_feedback": "Yaxshi tushuntirilgan."},
        format="json",
    )
    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["answer"]["points_awarded"] == 3.5
    assert body["answer"]["teacher_feedback"] == "Yaxshi tushuntirilgan."
    assert body["answer"]["graded_by"]["id"] == str(world.teacher.id)
    assert body["answer"]["graded_at"] is not None
    # 2 + 3 + 1 (objective) + 3.5 = 9.5 / 10
    assert body["attempt"] == {
        "id": str(submitted.id),
        "status": "GRADED",
        "score": 9.5,
        "percentage": 95,
        "passed": True,
    }
    submitted.refresh_from_db()
    assert submitted.status == AttemptStatus.GRADED and submitted.score == Decimal("9.50")
    assert auth_client(world.teacher).get(PENDING).json()["data"] == []  # navbatdan chiqdi


def test_student_sees_result_only_after_grading(api, auth_client, world, submitted):
    client = api(world.student)
    before = client.detail(submitted.id).json()
    assert before["status"] == "PENDING_GRADING" and before["score"] is None

    auth_client(world.teacher).patch(
        grade_url(open_answer(submitted, world)), {"points_awarded": 4}, format="json"
    )
    after = client.detail(submitted.id).json()
    assert after["status"] == "GRADED" and after["score"] == 10 and after["passed"] is True


def test_attempt_stays_pending_until_every_open_answer_is_graded(auth_client, api, make_world):
    world = make_world()
    second = ExamQuestionFactory(
        exam=world.exam,
        question=QuestionFactory(
            course=world.course,
            module=world.q["open"].module,
            type=QuestionType.OPEN_ENDED,
            options=False,
        ),
        points=6,
        position=5,
    )
    assignment = AssignmentFactory(
        exam=world.exam, published_by=world.teacher, ensure_question=False
    )
    client = api(world.student)
    attempt_id = client.start(assignment).json()["id"]
    client.answer(attempt_id, world.eq["open"], text_answer="first")
    client.answer(attempt_id, second, text_answer="second")
    client.submit(attempt_id)
    teacher = auth_client(world.teacher)
    first_answer = StudentAnswer.objects.get(
        attempt_id=attempt_id,
        attempt_question__snapshot_question__source_exam_question_id=world.eq["open"].id,
    )
    second_answer = StudentAnswer.objects.get(
        attempt_id=attempt_id,
        attempt_question__snapshot_question__source_exam_question_id=second.id,
    )

    one = teacher.patch(grade_url(first_answer), {"points_awarded": 4}, format="json").json()
    assert one["attempt"]["status"] == "PENDING_GRADING" and one["attempt"]["score"] is None
    row = teacher.get(PENDING).json()["data"][0]
    assert row["pending_answers_count"] == 1

    two = teacher.patch(grade_url(second_answer), {"points_awarded": 6}, format="json").json()
    assert two["attempt"]["status"] == "GRADED"
    assert two["attempt"]["score"] == 10  # 0 (objective javobsiz) + 4 + 6
    assert two["attempt"]["percentage"] == 62.5  # 10 / 16


def test_regrading_updates_the_result(auth_client, world, submitted):
    teacher = auth_client(world.teacher)
    answer = open_answer(submitted, world)
    teacher.patch(grade_url(answer), {"points_awarded": 4}, format="json")
    again = teacher.patch(
        grade_url(answer),
        {"points_awarded": 0, "teacher_feedback": "Qayta ko‘rildi"},
        format="json",
    ).json()
    assert again["attempt"]["score"] == 6 and again["attempt"]["percentage"] == 60
    assert again["attempt"]["status"] == "GRADED"


def test_feedback_is_kept_when_only_points_change(auth_client, world, submitted):
    teacher = auth_client(world.teacher)
    answer = open_answer(submitted, world)
    teacher.patch(
        grade_url(answer), {"points_awarded": 1, "teacher_feedback": "Birinchi izoh"}, format="json"
    )
    teacher.patch(grade_url(answer), {"points_awarded": 2}, format="json")
    answer.refresh_from_db()
    assert answer.teacher_feedback == "Birinchi izoh" and answer.points_awarded == 2


@pytest.mark.parametrize("points", [4.01, 100])
def test_points_cannot_exceed_the_question_maximum(auth_client, world, submitted, points):
    response = auth_client(world.teacher).patch(
        grade_url(open_answer(submitted, world)), {"points_awarded": points}, format="json"
    )
    assert response.status_code == 400
    assert "4" in response.json()["message"]
    submitted.refresh_from_db()
    assert submitted.status == AttemptStatus.PENDING_GRADING


@pytest.mark.parametrize(
    "payload", [{"points_awarded": -1}, {"points_awarded": "abc"}, {}, {"points_awarded": 1.234}]
)
def test_invalid_grade_payloads_return_422(auth_client, world, submitted, payload):
    response = auth_client(world.teacher).patch(
        grade_url(open_answer(submitted, world)), payload, format="json"
    )
    assert response.status_code == 422


def test_zero_points_is_a_valid_grade(auth_client, world, submitted):
    response = auth_client(world.teacher).patch(
        grade_url(open_answer(submitted, world)), {"points_awarded": 0}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["attempt"]["score"] == 6


def test_only_open_ended_answers_can_be_graded_manually(auth_client, world, submitted):
    objective = StudentAnswer.objects.get(
        attempt=submitted,
        attempt_question__snapshot_question__source_exam_question_id=world.eq["single"].id,
    )
    response = auth_client(world.teacher).patch(
        grade_url(objective), {"points_awarded": 1}, format="json"
    )
    assert response.status_code == 400
    objective.refresh_from_db()
    assert objective.points_awarded == 2


def test_cannot_grade_an_attempt_in_progress(auth_client, api, world):
    attempt_id = api(world.student).start(world.assignment).json()["id"]
    answer = StudentAnswer.objects.create(
        attempt_id=attempt_id, exam_question=world.eq["open"], text_answer="draft"
    )
    response = auth_client(world.teacher).patch(
        grade_url(answer), {"points_awarded": 1}, format="json"
    )
    assert response.status_code == 409


def test_grading_access_rules(auth_client, api_client, admin, world, submitted):
    url = grade_url(open_answer(submitted, world))
    body = {"points_awarded": 1}
    assert auth_client(world.student).patch(url, body, format="json").status_code == 403
    assert api_client.patch(url, body, format="json").status_code == 401

    outsider = TeacherFactory()
    CourseTeacherFactory(teacher=outsider)
    assert auth_client(outsider).patch(url, body, format="json").status_code == 404

    colleague = CourseTeacherFactory(
        course=world.course, type="SUPPORT"
    ).teacher  # boshqa teacher ham baholay oladi
    assert auth_client(colleague).patch(url, body, format="json").status_code == 200
    assert auth_client(admin).patch(url, {"points_awarded": 2}, format="json").status_code == 200


def test_unknown_answer_returns_404(auth_client, world):
    url = "/api/v1/answers/00000000-0000-4000-8000-000000000000/grade"
    assert (
        auth_client(world.teacher).patch(url, {"points_awarded": 1}, format="json").status_code
        == 404
    )


def test_staff_detail_shows_grader_after_grading(auth_client, world, submitted):
    auth_client(world.teacher).patch(
        grade_url(open_answer(submitted, world)), {"points_awarded": 2}, format="json"
    )
    body = auth_client(world.teacher).get(f"/api/v1/attempts/{submitted.id}").json()
    graded = [a for a in body["answers"] if a["graded_by"]]
    assert len(graded) == 1 and graded[0]["graded_by"]["id"] == str(world.teacher.id)
    event = AuditLog.objects.get(action=AuditAction.ANSWER_GRADED)
    assert event.actor == world.teacher
    assert event.entity_id == open_answer(submitted, world).id
    assert event.metadata["attempt_id"] == str(submitted.id)
    assert "teacher_feedback" not in event.metadata

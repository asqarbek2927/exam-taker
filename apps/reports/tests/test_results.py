from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.tests.factories import (
    CourseTeacherFactory,
    EnrollmentFactory,
    GroupStudentFactory,
    StudyGroupFactory,
)
from apps.assignments.choices import AudienceType
from apps.assignments.tests.factories import AssignmentFactory, add_groups
from apps.attempts.tests.factories import AttemptFactory
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

RESULTS = "/api/v1/results"


def finished(
    assignment, student, number=1, *, percentage=None, passed=None, status=None, days_ago=0
):
    """Yakunlangan attempt (default: GRADED, 80%, passed)."""
    status = status or "GRADED"
    graded = status == "GRADED"
    percentage = percentage if percentage is not None else (80 if graded else None)
    return AttemptFactory(
        assignment=assignment,
        student=student,
        attempt_number=number,
        status=status,
        percentage=percentage,
        score=(percentage / 10 if percentage is not None else None),
        passed=(passed if passed is not None else (percentage >= 50 if graded else None)),
        submitted_at=timezone.now() - timedelta(days=days_ago),
    )


@pytest.fixture
def ctx(teacher):
    assignment = AssignmentFactory()
    course = assignment.exam.course
    CourseTeacherFactory(course=course, teacher=teacher)
    students = [EnrollmentFactory(course=course).student for _ in range(3)]
    return {"teacher": teacher, "course": course, "assignment": assignment, "students": students}


def ids(client, **params):
    return [r["id"] for r in client.get(RESULTS, params).json()["data"]]


# ------------------------------- scoping -------------------------------
def test_each_role_sees_only_its_results(auth_client, admin, ctx):
    s1, s2, _ = ctx["students"]
    mine = finished(ctx["assignment"], s1)
    theirs = finished(ctx["assignment"], s2)
    foreign = finished(AssignmentFactory(), StudentFactory())

    assert set(ids(auth_client(s1))) == {str(mine.id)}
    assert set(ids(auth_client(ctx["teacher"]))) == {str(mine.id), str(theirs.id)}
    assert set(ids(auth_client(admin))) == {str(mine.id), str(theirs.id), str(foreign.id)}
    outsider = TeacherFactory()
    CourseTeacherFactory(teacher=outsider)
    assert ids(auth_client(outsider)) == []


def test_student_cannot_peek_at_others_via_filters(auth_client, ctx):
    s1, s2, _ = ctx["students"]
    finished(ctx["assignment"], s2)
    assert ids(auth_client(s1), student_id=s2.id) == []


def test_requires_authentication(api_client):
    assert api_client.get(RESULTS).status_code == 401


def test_in_progress_attempts_are_not_results(auth_client, ctx):
    student = ctx["students"][0]
    AttemptFactory(assignment=ctx["assignment"], student=student, attempt_number=2)
    done = finished(ctx["assignment"], student, 1)
    assert ids(auth_client(student)) == [str(done.id)]


def test_pending_grading_hides_score(auth_client, ctx):
    student = ctx["students"][0]
    pending = finished(ctx["assignment"], student, 1, status="PENDING_GRADING")
    row = auth_client(student).get(RESULTS).json()["data"][0]
    assert row["id"] == str(pending.id) and row["status"] == "PENDING_GRADING"
    assert (row["score"], row["percentage"], row["passed"]) == (None, None, None)


def test_row_shape(auth_client, ctx):
    group = StudyGroupFactory(course=ctx["course"], name="Frontend A")
    ctx["assignment"].audience_type = AudienceType.GROUPS
    ctx["assignment"].save(update_fields=["audience_type"])
    add_groups(ctx["assignment"], group)
    finished(ctx["assignment"], ctx["students"][0])
    row = auth_client(ctx["teacher"]).get(RESULTS).json()["data"][0]
    assert set(row) == {
        "id", "assignment_id", "exam_id", "exam_title", "course", "student", "attempt_number",
        "student_avatar_url", "audience_type", "groups", "status", "started_at", "submitted_at",
        "score", "percentage", "passed", "is_latest",
    }  # fmt: skip
    assert row["course"]["id"] == str(ctx["course"].id)
    assert row["student"]["id"] == str(ctx["students"][0].id)
    assert row["audience_type"] == "GROUPS"
    assert row["groups"] == [{"id": str(group.id), "name": "Frontend A"}]


def test_results_summary_matches_page_cards_and_is_role_scoped(auth_client, admin, ctx):
    s1, s2, s3 = ctx["students"]
    finished(ctx["assignment"], s1, percentage=88, passed=True)
    finished(ctx["assignment"], s2, percentage=74, passed=True)
    finished(ctx["assignment"], s3, status="PENDING_GRADING")
    finished(AssignmentFactory(), StudentFactory(), percentage=10, passed=False)

    teacher_summary = auth_client(ctx["teacher"]).get(f"{RESULTS}/summary")
    assert teacher_summary.status_code == 200
    assert teacher_summary.json() == {
        "submissions": 3,
        "awaiting_review": 1,
        "graded": 2,
        "average_score": 81.0,
        "grading_progress_percentage": 67,
    }
    assert auth_client(admin).get(f"{RESULTS}/summary").json()["submissions"] == 4


def test_results_search_includes_course_name(auth_client, admin, ctx):
    result = finished(ctx["assignment"], ctx["students"][0])
    response = auth_client(admin).get(RESULTS, {"search": ctx["course"].name})
    assert [item["id"] for item in response.json()["data"]] == [str(result.id)]


# ------------------------------- latest -------------------------------
def test_latest_only_and_is_latest(auth_client, admin, ctx):
    s1, s2, _ = ctx["students"]
    first = finished(ctx["assignment"], s1, 1, percentage=40, passed=False, days_ago=3)
    second = finished(ctx["assignment"], s1, 2, percentage=80, passed=True, days_ago=2)
    AttemptFactory(assignment=ctx["assignment"], student=s1, attempt_number=3)  # IN_PROGRESS
    other = finished(ctx["assignment"], s2, 1, percentage=60)
    other_assignment = finished(AssignmentFactory(), s1, 1)
    client = auth_client(admin)

    assert set(ids(client)) == {
        str(first.id),
        str(second.id),
        str(other.id),
        str(other_assignment.id),
    }
    assert set(ids(client, latest_only="true")) == {
        str(second.id),
        str(other.id),
        str(other_assignment.id),
    }
    flags = {r["id"]: r["is_latest"] for r in client.get(RESULTS).json()["data"]}
    assert flags[str(first.id)] is False and flags[str(second.id)] is True
    assert flags[str(other.id)] is True


def test_latest_result_may_be_pending_grading(auth_client, ctx):
    student = ctx["students"][0]
    finished(ctx["assignment"], student, 1, percentage=90)
    pending = finished(ctx["assignment"], student, 2, status="PENDING_GRADING")
    assert ids(auth_client(student), latest_only="true") == [str(pending.id)]


# ------------------------------- filters -------------------------------
def test_filters(auth_client, admin, ctx):
    s1, s2, s3 = ctx["students"]
    passed = finished(ctx["assignment"], s1, 1, percentage=90, passed=True, days_ago=10)
    failed = finished(ctx["assignment"], s2, 1, percentage=30, passed=False, days_ago=1)
    pending = finished(ctx["assignment"], s3, 1, status="PENDING_GRADING", days_ago=0)
    foreign = finished(AssignmentFactory(), StudentFactory())
    group = StudyGroupFactory(course=ctx["course"])
    GroupStudentFactory(group=group, student=s1)
    client = auth_client(admin)
    base = {str(passed.id), str(failed.id), str(pending.id)}

    assert set(ids(client, course_id=ctx["course"].id)) == base
    assert set(ids(client, exam_id=ctx["assignment"].exam_id)) == base
    assert set(ids(client, assignment_id=ctx["assignment"].id)) == base
    assert set(ids(client, student_id=s2.id)) == {str(failed.id)}
    assert set(ids(client, group_id=group.id)) == {str(passed.id)}
    assert set(ids(client, teacher_id=ctx["assignment"].published_by_id)) == base
    assert set(ids(client, teacher_id=foreign.assignment.published_by_id)) == {str(foreign.id)}
    assert set(ids(client, status="PENDING_GRADING")) == {str(pending.id)}
    assert set(ids(client, passed="true", course_id=ctx["course"].id)) == {str(passed.id)}
    assert set(ids(client, passed="false", course_id=ctx["course"].id)) == {str(failed.id)}

    today = timezone.localdate()
    assert set(ids(client, date_from=today - timedelta(days=2), course_id=ctx["course"].id)) == {
        str(failed.id),
        str(pending.id),
    }
    assert set(ids(client, date_to=today - timedelta(days=5), course_id=ctx["course"].id)) == {
        str(passed.id)
    }


@pytest.mark.parametrize(
    "params", [{"status": "IN_PROGRESS"}, {"date_from": "yesterday"}, {"student_id": "x"}]
)
def test_invalid_filters_return_422(auth_client, admin, params):
    assert auth_client(admin).get(RESULTS, params).status_code == 422


def test_ordering(auth_client, admin, ctx):
    s1, s2, _ = ctx["students"]
    old = finished(ctx["assignment"], s1, 1, percentage=90, days_ago=5)
    new = finished(ctx["assignment"], s2, 1, percentage=30, days_ago=1)
    client = auth_client(admin)
    assert ids(client) == [str(new.id), str(old.id)]  # eng yangisi birinchi
    assert ids(client, ordering="percentage") == [str(new.id), str(old.id)]
    assert ids(client, ordering="-percentage") == [str(old.id), str(new.id)]


def test_expired_in_progress_attempt_becomes_a_result(auth_client, ctx):
    student = ctx["students"][0]
    attempt = AttemptFactory(
        assignment=ctx["assignment"],
        student=student,
        deadline_at=timezone.now() - timedelta(minutes=10),
    )
    assert ids(auth_client(student)) == [str(attempt.id)]
    attempt.refresh_from_db()
    assert attempt.status in ("GRADED", "PENDING_GRADING")


def test_pagination_and_query_count(auth_client, admin, ctx, django_assert_max_num_queries):
    for number, student in enumerate(ctx["students"] * 3, start=1):
        finished(ctx["assignment"], student, number)
    with django_assert_max_num_queries(6):
        body = auth_client(admin).get(RESULTS, {"limit": 4}).json()
    assert body["pagination"]["limit"] == 4 and len(body["data"]) <= 4

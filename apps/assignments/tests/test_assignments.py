from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics.choices import CourseStatus, EnrollmentStatus
from apps.academics.models import StudyGroup
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    GroupStudentFactory,
    StudyGroupFactory,
)
from apps.assignments.choices import AssignmentStatus, AudienceType
from apps.assignments.models import ExamAssignment, ExamAssignmentRecipient
from apps.assignments.selectors import (
    effective_status_of,
    eligible_students,
    staff_assignments,
    with_effective_status,
)
from apps.assignments.tests.factories import AssignmentFactory, add_groups, add_students
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory, ExamQuestionFactory
from apps.notifications.models import Notification
from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/exam-assignments"


def iso(delta: timedelta) -> str:
    return (timezone.now() + delta).isoformat()


@pytest.fixture
def ctx(teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    exam = ExamFactory(course=course, created_by=teacher, status=ExamStatus.READY)
    ExamQuestionFactory(exam=exam, question__course=course)
    group = StudyGroupFactory(course=course)
    in_group = EnrollmentFactory(course=course).student
    GroupStudentFactory(group=group, student=in_group)
    outside = EnrollmentFactory(course=course).student
    return {
        "teacher": teacher,
        "course": course,
        "exam": exam,
        "group": group,
        "in_group": in_group,
        "outside": outside,
    }


def payload(ctx, **overrides):
    data = {
        "exam_id": str(ctx["exam"].id),
        "audience_type": "ALL_COURSE_STUDENTS",
        "start_at": iso(timedelta(hours=-1)),
        "end_at": iso(timedelta(days=1)),
        "duration_minutes": 30,
        "max_attempts": 2,
    }
    data.update(overrides)
    return data


def create(client, ctx, **overrides):
    return client.post(URL, payload(ctx, **overrides), format="json")


# ------------------------------- create -------------------------------
def test_create_for_all_course_students(auth_client, ctx):
    response = create(auth_client(ctx["teacher"]), ctx)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["stored_status"] == "PUBLISHED"
    assert body["audience_type"] == "ALL_COURSE_STUDENTS"
    assert body["groups"] == [] and body["students"] == []
    assert body["published_by"]["id"] == str(ctx["teacher"].id)
    assert body["exam"]["id"] == str(ctx["exam"].id)
    assert body["course"]["id"] == str(ctx["course"].id)
    assert body["max_attempts"] == 2 and body["duration_minutes"] == 30
    assert body["attempts_count"] == 0
    assert body["eligible_students_count"] == 2
    assignment = ExamAssignment.objects.get(pk=body["id"])
    assert set(
        ExamAssignmentRecipient.objects.filter(assignment=assignment).values_list(
            "student_id", flat=True
        )
    ) == {ctx["in_group"].id, ctx["outside"].id}
    notifications = Notification.objects.filter(
        recipient_id__in=[ctx["in_group"].id, ctx["outside"].id]
    )
    assert notifications.count() == 2
    assert {item.data["assignment_id"] for item in notifications} == {str(assignment.id)}


def test_create_for_groups_and_specific_students(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    groups = create(client, ctx, audience_type="GROUPS", group_ids=[str(ctx["group"].id)]).json()
    assert [g["id"] for g in groups["groups"]] == [str(ctx["group"].id)]
    assert groups["eligible_students_count"] == 1

    specific = create(
        client,
        ctx,
        audience_type="SPECIFIC_STUDENTS",
        student_ids=[str(ctx["outside"].id), str(ctx["in_group"].id)],
    ).json()
    assert {s["id"] for s in specific["students"]} == {
        str(ctx["outside"].id),
        str(ctx["in_group"].id),
    }
    assert specific["eligible_students_count"] == 2


def test_create_as_draft_and_scheduled(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    draft = create(client, ctx, is_draft=True).json()
    assert draft["status"] == "DRAFT" and draft["stored_status"] == "DRAFT"

    scheduled = create(client, ctx, start_at=iso(timedelta(hours=2))).json()
    assert scheduled["status"] == "SCHEDULED"


def test_create_without_deadline_and_with_unlimited_attempts(auth_client, ctx):
    body = create(auth_client(ctx["teacher"]), ctx, end_at=None, max_attempts=None).json()
    assert body["end_at"] is None
    assert body["max_attempts"] is None
    assert body["status"] == "ACTIVE"


def test_draft_may_have_past_deadline_but_published_may_not(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    past = {"start_at": iso(timedelta(days=-2)), "end_at": iso(timedelta(days=-1))}
    assert create(client, ctx, is_draft=True, **past).status_code == 201
    rejected = create(client, ctx, **past)
    assert rejected.status_code == 400
    assert "o‘tib ketgan" in rejected.json()["message"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"end_at": None, "max_attempts": 0},
        {"duration_minutes": 0},
        {"duration_minutes": 1441},
        {"max_attempts": -1},
        {"audience_type": "EVERYONE"},
        {"audience_type": "GROUPS"},  # group_ids yo‘q
        {"audience_type": "SPECIFIC_STUDENTS"},  # student_ids yo‘q
        {"group_ids": ["00000000-0000-4000-8000-000000000000"]},  # ALL + group_ids
        {"exam_id": "00000000-0000-4000-8000-000000000000"},
        {"exam_id": "nope"},
    ],
)
def test_create_validation_errors_return_422(auth_client, ctx, overrides):
    response = create(auth_client(ctx["teacher"]), ctx, **overrides)
    assert response.status_code == 422, response.json()


def test_end_must_be_after_start(auth_client, ctx):
    response = create(
        auth_client(ctx["teacher"]),
        ctx,
        start_at=iso(timedelta(hours=1)),
        end_at=iso(timedelta(minutes=30)),
    )
    assert response.status_code == 422
    assert "end_at" in response.json()["errors"]


def test_end_at_and_max_attempts_keys_are_required(auth_client, ctx):
    data = payload(ctx)
    del data["end_at"], data["max_attempts"]
    response = auth_client(ctx["teacher"]).post(URL, data, format="json")
    assert response.status_code == 422
    assert {"end_at", "max_attempts"} <= set(response.json()["errors"])


def test_only_ready_exam_with_questions_can_be_published(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    draft_exam = ExamFactory(course=ctx["course"], status=ExamStatus.DRAFT)
    ExamQuestionFactory(exam=draft_exam, question__course=ctx["course"])
    assert create(client, ctx, exam_id=str(draft_exam.id)).status_code == 400

    empty = ExamFactory(course=ctx["course"], status=ExamStatus.READY)
    assert create(client, ctx, exam_id=str(empty.id)).status_code == 400

    archived = ExamFactory(course=ctx["course"], status=ExamStatus.ARCHIVED)
    assert create(client, ctx, exam_id=str(archived.id)).status_code == 400


def test_audience_must_belong_to_exam_course(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    foreign_group = StudyGroupFactory()
    response = create(client, ctx, audience_type="GROUPS", group_ids=[str(foreign_group.id)])
    assert response.status_code == 400

    stranger = StudentFactory()  # kursga yozilmagan
    response = create(
        client, ctx, audience_type="SPECIFIC_STUDENTS", student_ids=[str(stranger.id)]
    )
    assert response.status_code == 400
    assert stranger.full_name in response.json()["message"]

    removed = EnrollmentFactory(course=ctx["course"], status=EnrollmentStatus.REMOVED).student
    response = create(client, ctx, audience_type="SPECIFIC_STUDENTS", student_ids=[str(removed.id)])
    assert response.status_code == 400


def test_duplicate_groups_or_students_are_rejected(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    gid = str(ctx["group"].id)
    assert create(client, ctx, audience_type="GROUPS", group_ids=[gid, gid]).status_code == 400
    sid = str(ctx["outside"].id)
    response = create(client, ctx, audience_type="SPECIFIC_STUDENTS", student_ids=[sid, sid])
    assert response.status_code == 400


def test_create_access_rules(auth_client, api_client, admin, student, ctx):
    assert create(auth_client(TeacherFactory()), ctx).status_code == 403
    assert create(auth_client(student), ctx).status_code == 403
    assert create(auth_client(admin), ctx).status_code == 201
    assert api_client.post(URL, payload(ctx), format="json").status_code == 401

    ctx["course"].status = CourseStatus.ARCHIVED
    ctx["course"].save()
    assert create(auth_client(ctx["teacher"]), ctx).status_code == 400


# ------------------------------- status -------------------------------
def test_effective_status_python_and_orm_agree():
    now = timezone.now()
    day = timedelta(days=1)
    cases = {
        "DRAFT": {"status": AssignmentStatus.DRAFT},
        "SCHEDULED": {"start_at": now + day},
        "ACTIVE": {},
        "ACTIVE-no-deadline": {"end_at": None},
        "COMPLETED-by-time": {"start_at": now - 2 * day, "end_at": now - day},
        "COMPLETED-manual": {"status": AssignmentStatus.COMPLETED},
        "PAUSED": {"status": AssignmentStatus.PAUSED},
        "PAUSED-future": {"status": AssignmentStatus.PAUSED, "start_at": now + day},
        "CANCELLED": {"status": AssignmentStatus.CANCELLED},
    }
    expected = {
        "DRAFT": "DRAFT",
        "SCHEDULED": "SCHEDULED",
        "ACTIVE": "ACTIVE",
        "ACTIVE-no-deadline": "ACTIVE",
        "COMPLETED-by-time": "COMPLETED",
        "COMPLETED-manual": "COMPLETED",
        "PAUSED": "PAUSED",
        "PAUSED-future": "PAUSED",
        "CANCELLED": "CANCELLED",
    }
    created = {name: AssignmentFactory(**kwargs) for name, kwargs in cases.items()}
    annotated = {
        a.pk: a.effective_status for a in with_effective_status(ExamAssignment.objects.all(), now)
    }
    for name, assignment in created.items():
        assert effective_status_of(assignment, now) == expected[name], name
        assert annotated[assignment.pk] == expected[name], name


def test_end_boundary_is_exclusive():
    now = timezone.now()
    assignment = AssignmentFactory(start_at=now - timedelta(hours=1), end_at=now)
    assert effective_status_of(assignment, now) == "COMPLETED"
    assert effective_status_of(assignment, now - timedelta(seconds=1)) == "ACTIVE"


def test_list_filters_by_effective_status(auth_client, admin):
    now = timezone.now()
    scheduled = AssignmentFactory(start_at=now + timedelta(days=1), end_at=None)
    active = AssignmentFactory()
    done = AssignmentFactory(start_at=now - timedelta(days=2), end_at=now - timedelta(days=1))
    draft = AssignmentFactory(status=AssignmentStatus.DRAFT)
    client = auth_client(admin)

    def ids(status):
        return {a["id"] for a in client.get(URL, {"status": status}).json()["data"]}

    assert ids("SCHEDULED") == {str(scheduled.id)}
    assert ids("ACTIVE") == {str(active.id)}
    assert ids("COMPLETED") == {str(done.id)}
    assert ids("DRAFT") == {str(draft.id)}
    assert client.get(URL, {"status": "NOPE"}).status_code == 422


def test_list_other_filters_and_scoping(auth_client, ctx):
    mine = AssignmentFactory(exam=ctx["exam"], published_by=ctx["teacher"], ensure_question=False)
    colleague = CourseTeacherFactory(course=ctx["course"], type="SUPPORT").teacher
    theirs = AssignmentFactory(exam=ctx["exam"], published_by=colleague, ensure_question=False)
    foreign = AssignmentFactory()
    client = auth_client(ctx["teacher"])

    ids = {a["id"] for a in client.get(URL).json()["data"]}
    assert ids == {str(mine.id), str(theirs.id)}
    assert client.get(f"{URL}/{foreign.id}").status_code == 404
    assert {a["id"] for a in client.get(URL, {"exam_id": ctx["exam"].id}).json()["data"]} == ids
    assert client.get(URL, {"course_id": foreign.exam.course_id}).json()["data"] == []


def test_assignment_directory_summary_is_role_scoped_and_ignores_archived(
        auth_client, admin, ctx
):
    now = timezone.now()
    mine = {
        "exam": ctx["exam"],
        "published_by": ctx["teacher"],
        "ensure_question": False,
    }
    AssignmentFactory(**mine)
    AssignmentFactory(start_at=now + timedelta(days=1), end_at=None, **mine)
    AssignmentFactory(status=AssignmentStatus.PAUSED, **mine)
    AssignmentFactory(status=AssignmentStatus.DRAFT, **mine)
    AssignmentFactory(status=AssignmentStatus.CANCELLED, is_archived=True, **mine)
    foreign = AssignmentFactory()

    teacher_summary = auth_client(ctx["teacher"]).get(f"{URL}/summary")
    assert teacher_summary.status_code == 200
    assert teacher_summary.json() == {
        "assignments": 4,
        "active": 1,
        "scheduled": 1,
        "paused": 1,
    }

    admin_summary = auth_client(admin).get(f"{URL}/summary").json()
    assert admin_summary["assignments"] == 5
    assert admin_summary["active"] == 2
    assert str(foreign.id) in {a["id"] for a in auth_client(admin).get(URL).json()["data"]}
    assert auth_client(ctx["outside"]).get(f"{URL}/summary").status_code == 403


def test_assignment_directory_scope_archive_and_course_search(auth_client, ctx):
    current = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], ensure_question=False
    )
    archived = AssignmentFactory(
        exam=ctx["exam"],
        published_by=ctx["teacher"],
        status=AssignmentStatus.CANCELLED,
        is_archived=True,
        archived_at=timezone.now(),
        ensure_question=False,
    )
    client = auth_client(ctx["teacher"])

    assert {a["id"] for a in client.get(URL).json()["data"]} == {str(current.id)}
    archived_data = client.get(URL, {"scope": "archived"}).json()["data"]
    assert {a["id"] for a in archived_data} == {str(archived.id)}
    assert archived_data[0]["is_archived"] is True
    assert {a["id"] for a in client.get(URL, {"scope": "all"}).json()["data"]} == {
        str(current.id),
        str(archived.id),
    }
    assert {a["id"] for a in client.get(URL, {"search": ctx["course"].name}).json()["data"]} == {
        str(current.id)
    }


def test_archive_and_unarchive_assignment(auth_client, ctx):
    completed = AssignmentFactory(
        exam=ctx["exam"],
        published_by=ctx["teacher"],
        status=AssignmentStatus.COMPLETED,
        ensure_question=False,
    )
    active = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], ensure_question=False
    )
    client = auth_client(ctx["teacher"])

    archived = client.post(f"{URL}/{completed.id}/archive")
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert archived.json()["archived_at"] is not None
    assert client.patch(
        f"{URL}/{completed.id}", {"duration_minutes": 10}, format="json"
    ).status_code == 400
    assert client.post(f"{URL}/{active.id}/archive").status_code == 400

    restored = client.post(f"{URL}/{completed.id}/unarchive")
    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False
    assert restored.json()["archived_at"] is None


def test_list_has_no_n_plus_one(auth_client, admin, django_assert_max_num_queries):
    for _ in range(6):
        assignment = AssignmentFactory(audience_type=AudienceType.GROUPS)
        add_groups(assignment, StudyGroupFactory(course=assignment.exam.course))
    with django_assert_max_num_queries(8):
        assert auth_client(admin).get(URL).status_code == 200


# ------------------------------- transitions -------------------------------
ALLOWED = {
    ("publish", "DRAFT"): "PUBLISHED",
    ("pause", "PUBLISHED"): "PAUSED",
    ("resume", "PAUSED"): "PUBLISHED",
    ("complete", "PUBLISHED"): "COMPLETED",
    ("complete", "PAUSED"): "COMPLETED",
    ("cancel", "DRAFT"): "CANCELLED",
    ("cancel", "PUBLISHED"): "CANCELLED",
    ("cancel", "PAUSED"): "CANCELLED",
    ("restore", "CANCELLED"): "DRAFT",
}


@pytest.mark.parametrize("action", ["publish", "pause", "resume", "complete", "cancel", "restore"])
@pytest.mark.parametrize("stored", ["DRAFT", "PUBLISHED", "PAUSED", "COMPLETED", "CANCELLED"])
def test_transition_matrix(auth_client, ctx, action, stored):
    assignment = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], status=stored, ensure_question=False
    )
    response = auth_client(ctx["teacher"]).post(f"{URL}/{assignment.id}/{action}")
    if (action, stored) in ALLOWED:
        assert response.status_code == 200, response.json()
        assert response.json()["stored_status"] == ALLOWED[(action, stored)]
    else:
        assert response.status_code == 409
    assignment.refresh_from_db()
    assert assignment.status == ALLOWED.get((action, stored), stored)


def test_cancelled_cannot_jump_to_active_only_via_restore_and_publish(auth_client, ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], status="CANCELLED", ensure_question=False
    )
    client = auth_client(ctx["teacher"])
    assert client.post(f"{URL}/{assignment.id}/publish").status_code == 409
    assert client.post(f"{URL}/{assignment.id}/restore").json()["status"] == "DRAFT"
    assert client.post(f"{URL}/{assignment.id}/publish").json()["status"] == "ACTIVE"
    assert set(assignment.recipients.values_list("student_id", flat=True)) == {
        ctx["in_group"].id,
        ctx["outside"].id,
    }


def test_publish_requires_ready_exam_and_future_deadline(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    draft = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], status="DRAFT", ensure_question=False
    )
    ctx["exam"].status = ExamStatus.DRAFT
    ctx["exam"].save()
    assert client.post(f"{URL}/{draft.id}/publish").status_code == 400

    ctx["exam"].status = ExamStatus.READY
    ctx["exam"].save()
    draft.start_at = timezone.now() - timedelta(days=2)
    draft.end_at = timezone.now() - timedelta(days=1)
    draft.save()
    assert client.post(f"{URL}/{draft.id}/publish").status_code == 400


def test_only_publisher_or_admin_can_modify(auth_client, admin, ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], ensure_question=False
    )
    colleague = CourseTeacherFactory(course=ctx["course"], type="SUPPORT").teacher
    client = auth_client(colleague)
    url = f"{URL}/{assignment.id}"

    assert client.get(url).status_code == 200
    assert client.patch(url, {"duration_minutes": 10}, format="json").status_code == 403
    assert client.post(f"{url}/pause").status_code == 403
    assert client.post(f"{url}/cancel").status_code == 403
    assert auth_client(admin).post(f"{url}/pause").status_code == 200


# ------------------------------- update -------------------------------
def test_update_draft_fields_and_audience(auth_client, ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"],
        published_by=ctx["teacher"],
        status="DRAFT",
        audience_type=AudienceType.GROUPS,
        ensure_question=False,
    )
    add_groups(assignment, ctx["group"])
    client = auth_client(ctx["teacher"])
    url = f"{URL}/{assignment.id}"

    changed = client.patch(
        url, {"duration_minutes": 45, "max_attempts": None, "end_at": None}, format="json"
    ).json()
    assert changed["duration_minutes"] == 45
    assert changed["max_attempts"] is None and changed["end_at"] is None
    assert [g["id"] for g in changed["groups"]] == [str(ctx["group"].id)]  # audience tegilmagan

    swapped = client.patch(
        url,
        {"audience_type": "SPECIFIC_STUDENTS", "student_ids": [str(ctx["outside"].id)]},
        format="json",
    ).json()
    assert swapped["groups"] == []
    assert [s["id"] for s in swapped["students"]] == [str(ctx["outside"].id)]

    to_all = client.patch(url, {"audience_type": "ALL_COURSE_STUDENTS"}, format="json").json()
    assert to_all["groups"] == [] and to_all["students"] == []


def test_update_validation(auth_client, ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], ensure_question=False
    )
    client = auth_client(ctx["teacher"])
    url = f"{URL}/{assignment.id}"

    bad_range = {"end_at": iso(timedelta(hours=-2))}  # start_at (-1h) dan oldin
    assert client.patch(url, bad_range, format="json").status_code == 400
    # audience_type ni GROUPS ga almashtirib, guruh bermaslik
    assert client.patch(url, {"audience_type": "GROUPS"}, format="json").status_code == 400
    assert client.patch(url, {"duration_minutes": 0}, format="json").status_code == 422


@pytest.mark.parametrize("stored", ["COMPLETED", "CANCELLED"])
def test_finished_assignments_cannot_be_edited(auth_client, ctx, stored):
    assignment = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], status=stored, ensure_question=False
    )
    response = auth_client(ctx["teacher"]).patch(
        f"{URL}/{assignment.id}", {"duration_minutes": 10}, format="json"
    )
    assert response.status_code == 400


def test_assignment_with_attempts_only_allows_extending_end_at(auth_client, ctx):
    from apps.attempts.tests.factories import AttemptFactory

    assignment = AssignmentFactory(
        exam=ctx["exam"], published_by=ctx["teacher"], ensure_question=False
    )
    AttemptFactory(assignment=assignment, student=ctx["outside"])
    client = auth_client(ctx["teacher"])
    url = f"{URL}/{assignment.id}"

    assert client.patch(url, {"duration_minutes": 5}, format="json").status_code == 409
    assert client.patch(url, {"max_attempts": 9}, format="json").status_code == 409
    assert (
            client.patch(url, {"audience_type": "ALL_COURSE_STUDENTS"}, format="json").status_code
            == 409
    )
    assert (
            client.patch(url, {"end_at": iso(timedelta(hours=3))}, format="json").status_code == 409
    )  # qisqartirish

    extended = client.patch(url, {"end_at": iso(timedelta(days=3))}, format="json")
    assert extended.status_code == 200
    assert (
            client.patch(url, {"end_at": None}, format="json").status_code == 200
    )  # deadline olib tashlandi


# ------------------------------- student view -------------------------------
def test_student_sees_only_eligible_assignments(auth_client, ctx):
    all_students = AssignmentFactory(exam=ctx["exam"], ensure_question=False)
    groups_only = AssignmentFactory(
        exam=ctx["exam"], audience_type=AudienceType.GROUPS, ensure_question=False
    )
    add_groups(groups_only, ctx["group"])
    specific = AssignmentFactory(
        exam=ctx["exam"], audience_type=AudienceType.SPECIFIC_STUDENTS, ensure_question=False
    )
    add_students(specific, ctx["outside"])
    AssignmentFactory(exam=ctx["exam"], status="DRAFT", ensure_question=False)
    AssignmentFactory(exam=ctx["exam"], status="CANCELLED", ensure_question=False)
    paused = AssignmentFactory(exam=ctx["exam"], status="PAUSED", ensure_question=False)
    AssignmentFactory()  # boshqa kurs

    def visible(student):
        data = auth_client(student).get(URL).json()["data"]
        return {a["id"] for a in data}

    assert visible(ctx["in_group"]) == {str(all_students.id), str(groups_only.id), str(paused.id)}
    assert visible(ctx["outside"]) == {str(all_students.id), str(specific.id), str(paused.id)}
    assert visible(StudentFactory()) == set()


def test_student_dto_and_can_start_flags(auth_client, ctx):
    active = AssignmentFactory(exam=ctx["exam"], max_attempts=1, ensure_question=False)
    paused = AssignmentFactory(exam=ctx["exam"], status="PAUSED", ensure_question=False)
    future = AssignmentFactory(
        exam=ctx["exam"],
        start_at=timezone.now() + timedelta(days=1),
        end_at=None,
        ensure_question=False,
    )
    ExamQuestionFactory(exam=ctx["exam"], question__course=ctx["course"], points=3)
    data = {a["id"]: a for a in auth_client(ctx["outside"]).get(URL).json()["data"]}

    dto = data[str(active.id)]
    assert set(dto) == {
        "id", "exam_id", "exam_title", "course", "start_at", "end_at", "duration_minutes",
        "max_attempts", "status", "questions_count", "total_points", "attempts_used",
        "attempts_remaining", "active_attempt_id", "can_start",
    }  # fmt: skip
    assert dto["status"] == "ACTIVE" and dto["can_start"] is True
    assert dto["questions_count"] == 2 and dto["total_points"] == 5
    assert dto["attempts_used"] == 0 and dto["attempts_remaining"] == 1
    assert data[str(paused.id)]["status"] == "PAUSED" and data[str(paused.id)]["can_start"] is False
    assert (
        data[str(future.id)]["status"] == "SCHEDULED"
        and data[str(future.id)]["can_start"] is False
    )
    assert data[str(future.id)]["attempts_remaining"] == 2


def test_student_retrieve_and_write_restrictions(auth_client, ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"], audience_type=AudienceType.GROUPS, ensure_question=False
    )
    add_groups(assignment, ctx["group"])
    url = f"{URL}/{assignment.id}"

    assert auth_client(ctx["in_group"]).get(url).status_code == 200
    assert auth_client(ctx["outside"]).get(url).status_code == 404  # eligible emas
    client = auth_client(ctx["in_group"])
    assert client.post(f"{url}/pause").status_code == 403
    assert client.patch(url, {"duration_minutes": 1}, format="json").status_code == 403


# ------------------------------- eligibility -------------------------------
def test_eligible_students_respects_enrollment_status_and_user_status(ctx):
    assignment = AssignmentFactory(exam=ctx["exam"], ensure_question=False)
    assert {s.id for s in eligible_students(assignment)} == {
        ctx["in_group"].id,
        ctx["outside"].id,
    }

    ctx["outside"].status = UserStatus.INACTIVE
    ctx["outside"].save()
    EnrollmentFactory(course=ctx["course"], status=EnrollmentStatus.COMPLETED)
    assert {s.id for s in eligible_students(assignment)} == {ctx["in_group"].id}


def test_group_audience_requires_active_enrollment(ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"], audience_type=AudienceType.GROUPS, ensure_question=False
    )
    add_groups(assignment, ctx["group"])
    assert {s.id for s in eligible_students(assignment)} == {ctx["in_group"].id}

    enrollment = ctx["in_group"].enrollments.get(course=ctx["course"])
    enrollment.status = EnrollmentStatus.COMPLETED  # guruhda qoladi, lekin ACTIVE emas
    enrollment.save()
    assert list(eligible_students(assignment)) == []


def test_student_in_two_groups_is_counted_once(ctx):
    other_group = StudyGroupFactory(course=ctx["course"])
    GroupStudentFactory(group=other_group, student=ctx["in_group"])
    assignment = AssignmentFactory(
        exam=ctx["exam"], audience_type=AudienceType.GROUPS, ensure_question=False
    )
    add_groups(assignment, ctx["group"], other_group)
    assert eligible_students(assignment).count() == 1


# ------------------------------- DB himoyasi -------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"end_at": timezone.now() - timedelta(days=5)},  # end_at < start_at
        {"duration_minutes": 0},
        {"max_attempts": 0},
    ],
)
def test_db_constraints(overrides):
    exam = ExamFactory(status=ExamStatus.READY)
    data = {
        "exam": exam,
        "published_by": exam.created_by,
        "audience_type": AudienceType.ALL_COURSE_STUDENTS,
        "start_at": timezone.now(),
        "end_at": None,
        "duration_minutes": 10,
        "max_attempts": None,
    }
    data.update(overrides)
    with pytest.raises(IntegrityError), transaction.atomic():
        ExamAssignment.objects.create(**data)


def test_group_used_by_assignment_cannot_be_deleted(auth_client, admin, ctx):
    assignment = AssignmentFactory(
        exam=ctx["exam"], audience_type=AudienceType.GROUPS, ensure_question=False
    )
    add_groups(assignment, ctx["group"])
    url = f"/api/v1/courses/{ctx['course'].id}/groups/{ctx['group'].id}"
    response = auth_client(admin).delete(url)
    assert response.status_code == 409
    assert StudyGroup.objects.filter(pk=ctx["group"].pk).exists()


def test_staff_queryset_counts_attempts_once(ctx):
    from apps.attempts.tests.factories import AttemptFactory

    assignment = AssignmentFactory(exam=ctx["exam"], ensure_question=False)
    add_groups(assignment, ctx["group"], StudyGroupFactory(course=ctx["course"]))
    AttemptFactory(assignment=assignment, student=ctx["outside"], attempt_number=1, status="GRADED")
    AttemptFactory(assignment=assignment, student=ctx["outside"], attempt_number=2)
    row = staff_assignments(ExamAssignment.objects.filter(pk=assignment.pk)).get()
    assert row.attempts_count == 2

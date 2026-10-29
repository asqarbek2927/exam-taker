from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.academics.tests.factories import EnrollmentFactory, GroupStudentFactory, StudyGroupFactory
from apps.assignments.choices import AssignmentStatus, AudienceType
from apps.assignments.tests.factories import add_groups
from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt
from apps.attempts.tests.factories import AttemptFactory
from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db


def contains_key(node, key) -> bool:
    if isinstance(node, dict):
        return key in node or any(contains_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(contains_key(v, key) for v in node)
    return False


def test_start_returns_questions_without_correct_answers(api, world):
    response = api(world.student).start(world.assignment)
    assert response.status_code == 201, response.json()
    body = response.json()

    assert body["attempt_number"] == 1
    assert body["status"] == "IN_PROGRESS"
    assert body["assignment_id"] == str(world.assignment.id)
    assert body["duration_minutes"] == 30
    assert {q["id"] for q in body["questions"]} == {
        str(world.eq[k].id) for k in ("single", "multi", "tf", "open")
    }  # Tartib attempt boshida bir marta random qilinadi.
    first = next(q for q in body["questions"] if q["id"] == str(world.eq["single"].id))
    assert first["question_id"] == str(world.q["single"].id)
    assert first["points"] == 2 and first["answer"] is None
    assert set(first["options"][0]) == {"id", "text"}
    open_question = next(q for q in body["questions"] if q["id"] == str(world.eq["open"].id))
    assert open_question["options"] == []
    assert not contains_key(body, "is_correct")  # TZ 13.1


def test_deadline_is_start_plus_duration(api, world):
    before = timezone.now()
    body = api(world.student).start(world.assignment).json()
    started, deadline = parse_datetime(body["started_at"]), parse_datetime(body["deadline_at"])
    assert before <= started <= timezone.now()
    assert deadline - started == timedelta(minutes=30)
    assert abs(parse_datetime(body["server_now"]) - timezone.now()) < timedelta(seconds=5)


def test_delivery_and_grading_use_immutable_snapshot(api, make_world):
    world = make_world(open_ended=False)
    client = api(world.student)
    started = client.start(world.assignment).json()
    single_before = next(
        question
        for question in started["questions"]
        if question["id"] == str(world.eq["single"].id)
    )
    right_id = next(
        option["id"] for option in single_before["options"] if option["text"] == "Right"
    )
    single_exam_question_id = world.eq["single"].id

    world.q["single"].text = "CHANGED AFTER START"
    world.q["single"].save(update_fields=["text", "updated_at"])
    world.q["single"].options.update(is_correct=False)
    world.q["single"].options.filter(text="Wrong1").update(is_correct=True)
    world.eq["single"].delete()

    resumed = client.detail(started["id"]).json()
    single_after = next(
        question
        for question in resumed["questions"]
        if question["id"] == str(single_exam_question_id)
    )
    assert single_after["text"] == single_before["text"]
    assert single_after["options"] == single_before["options"]

    saved = client.answer(started["id"], single_exam_question_id, option_ids=[right_id])
    assert saved.status_code == 200
    result = client.submit(started["id"]).json()
    assert result["score"] == 2


def test_deadline_is_capped_by_assignment_end(api, make_world):
    world = make_world(end_at=timezone.now() + timedelta(minutes=10))
    body = api(world.student).start(world.assignment).json()
    deadline = parse_datetime(body["deadline_at"])
    assert deadline == world.assignment.end_at
    assert deadline - parse_datetime(body["started_at"]) < timedelta(minutes=11)


def test_no_deadline_assignment_uses_duration_only(api, make_world):
    world = make_world(end_at=None)
    body = api(world.student).start(world.assignment).json()
    delta = parse_datetime(body["deadline_at"]) - parse_datetime(body["started_at"])
    assert delta == timedelta(minutes=30)


def test_only_one_active_attempt_at_a_time(api, world):
    client = api(world.student)
    first = client.start(world.assignment)
    second = client.start(world.assignment)
    assert first.status_code == 201
    assert second.status_code == 409
    assert ExamAttempt.objects.count() == 1

    listing = client.client.get("/api/v1/exam-assignments").json()["data"][0]
    assert listing["active_attempt_id"] == first.json()["id"]
    assert listing["can_start"] is False
    assert listing["attempts_used"] == 1


def test_attempt_limit_and_numbering(api, make_world):
    world = make_world(max_attempts=2)
    client = api(world.student)
    numbers = []
    for _ in range(2):
        started = client.start(world.assignment).json()
        numbers.append(started["attempt_number"])
        assert client.submit(started["id"]).status_code == 200
    assert numbers == [1, 2]

    blocked = client.start(world.assignment)
    assert blocked.status_code == 409
    assert "limit" in blocked.json()["message"]
    listing = client.client.get("/api/v1/exam-assignments").json()["data"][0]
    assert listing["attempts_remaining"] == 0 and listing["can_start"] is False


def test_unlimited_attempts(api, make_world):
    world = make_world(max_attempts=None)
    client = api(world.student)
    for expected in (1, 2, 3, 4):
        started = client.start(world.assignment).json()
        assert started["attempt_number"] == expected
        client.submit(started["id"])
    listing = client.client.get("/api/v1/exam-assignments").json()["data"][0]
    assert listing["attempts_remaining"] is None and listing["can_start"] is True


def test_limit_is_per_student(api, make_world):
    world = make_world(max_attempts=1)
    other = StudentFactory()
    EnrollmentFactory(course=world.course, student=other)
    for student in (world.student, other):
        assert api(student).start(world.assignment).status_code == 201


def test_ineligible_students_get_404(api, world):
    stranger = StudentFactory()  # kursga yozilmagan
    assert api(stranger).start(world.assignment).status_code == 404

    removed = EnrollmentFactory(course=world.course, status="REMOVED").student
    assert api(removed).start(world.assignment).status_code == 404


def test_group_audience_is_enforced(api, make_world):
    world = make_world(audience_type=AudienceType.GROUPS)
    group = StudyGroupFactory(course=world.course)
    add_groups(world.assignment, group)
    outsider = world.student  # kursga yozilgan, lekin guruhda emas
    assert api(outsider).start(world.assignment).status_code == 404

    member = EnrollmentFactory(course=world.course).student
    GroupStudentFactory(group=group, student=member)
    assert api(member).start(world.assignment).status_code == 201


@pytest.mark.parametrize(
    ("overrides", "expected_status", "message"),
    [
        ({"start_at": timezone.now() + timedelta(hours=1), "end_at": None}, 400, "boshlanmagan"),
        ({"status": AssignmentStatus.PAUSED}, 400, "to‘xtatilgan"),
        ({"status": AssignmentStatus.COMPLETED}, 400, "yakunlangan"),
        (
            {
                "start_at": timezone.now() - timedelta(days=2),
                "end_at": timezone.now() - timedelta(days=1),
            },
            400,
            "yakunlangan",
        ),
        ({"status": AssignmentStatus.DRAFT}, 404, None),
        ({"status": AssignmentStatus.CANCELLED}, 404, None),
    ],
)
def test_start_depends_on_assignment_state(api, make_world, overrides, expected_status, message):
    world = make_world(**overrides)
    response = api(world.student).start(world.assignment)
    assert response.status_code == expected_status
    if message:
        assert message in response.json()["message"]
    assert ExamAttempt.objects.count() == 0


def test_staff_and_anonymous_cannot_start(auth_client, api_client, admin, world):
    url = f"/api/v1/exam-assignments/{world.assignment.id}/start"
    assert auth_client(world.teacher).post(url).status_code == 403
    assert auth_client(admin).post(url).status_code == 403
    assert api_client.post(url).status_code == 401


def test_inactive_student_cannot_start(api, world):
    world.student.status = UserStatus.INACTIVE
    world.student.save()
    assert api(world.student).start(world.assignment).status_code == 403


def test_expired_attempt_is_closed_before_new_one_starts(api, make_world):
    world = make_world(max_attempts=2)
    client = api(world.student)
    first = client.start(world.assignment).json()
    ExamAttempt.objects.filter(pk=first["id"]).update(
        started_at=timezone.now() - timedelta(hours=1),
        deadline_at=timezone.now() - timedelta(minutes=5),
    )

    second = client.start(world.assignment)
    assert second.status_code == 201
    assert second.json()["attempt_number"] == 2
    old = ExamAttempt.objects.get(pk=first["id"])
    assert old.status in (AttemptStatus.GRADED, AttemptStatus.PENDING_GRADING)
    assert old.submitted_at == old.deadline_at
    # Endi limit tugadi: muddati o‘tgan attempt ham hisobga olinadi.
    client.submit(second.json()["id"])
    assert client.start(world.assignment).status_code == 409


def test_db_allows_only_one_active_attempt_per_student_and_assignment(world):
    AttemptFactory(assignment=world.assignment, student=world.student)
    with pytest.raises(IntegrityError), transaction.atomic():
        AttemptFactory(assignment=world.assignment, student=world.student, attempt_number=2)


def test_db_allows_many_finished_attempts_but_unique_numbers(world):
    AttemptFactory(
        assignment=world.assignment, student=world.student, attempt_number=1, status="GRADED"
    )
    AttemptFactory(
        assignment=world.assignment, student=world.student, attempt_number=2, status="GRADED"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AttemptFactory(
            assignment=world.assignment, student=world.student, attempt_number=2, status="GRADED"
        )

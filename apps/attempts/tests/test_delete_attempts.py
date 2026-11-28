"""Test (sinov) attempt'larini natijalardan o'chirish: service va `delete_attempts` buyrug'i."""

import uuid
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.academics.tests.factories import EnrollmentFactory
from apps.attempts.models import (
    AttemptEvent,
    AttemptQuestion,
    ExamAttempt,
    StudentAnswer,
    StudentAnswerOption,
)
from apps.attempts.services import delete_attempts
from apps.attempts.tests.conftest import option_id
from apps.audit.choices import AuditAction
from apps.audit.models import AuditLog
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db


def _take(api, world, student):
    client = api(student)
    attempt_id = client.start(world.assignment).json()["id"]
    single = world.q["single"]
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(single, "Right")])
    client.answer(attempt_id, world.eq["open"], text_answer="test")
    client.client.post(
        f"/api/v1/attempts/{attempt_id}/events",
        {
            "event_id": str(uuid.uuid4()),
            "type": "COPY",
            "client_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )
    client.submit(attempt_id)
    return attempt_id


@pytest.fixture
def two_attempts(api, make_world):
    world = make_world()
    tester = world.student
    real = StudentFactory()
    EnrollmentFactory(course=world.course, student=real)
    return world, _take(api, world, tester), _take(api, world, real), tester, real


def test_plain_orm_delete_is_blocked_by_protect(two_attempts):
    """Shuning uchun maxsus service kerak (admin panel ham o'chira olmaydi)."""
    from django.db.models import ProtectedError

    _, test_id, *_ = two_attempts
    with pytest.raises(ProtectedError):
        ExamAttempt.objects.filter(pk=test_id).delete()


def test_service_deletes_attempt_with_all_children(two_attempts):
    world, test_id, real_id, *_ = two_attempts
    assert delete_attempts(ExamAttempt.objects.filter(pk=test_id)) == 1

    assert not ExamAttempt.objects.filter(pk=test_id).exists()
    assert not StudentAnswer.objects.filter(attempt_id=test_id).exists()
    assert not StudentAnswerOption.objects.filter(student_answer__attempt_id=test_id).exists()
    assert not AttemptQuestion.objects.filter(attempt_id=test_id).exists()
    assert not AttemptEvent.objects.filter(attempt_id=test_id).exists()
    # Boshqa studentning attempt'i, imtihon va savollar joyida.
    assert ExamAttempt.objects.filter(pk=real_id).exists()
    assert StudentAnswer.objects.filter(attempt_id=real_id).count() == 4
    assert world.exam.exam_questions.count() == 4


def test_deleted_attempt_disappears_from_results(auth_client, two_attempts):
    world, test_id, real_id, *_ = two_attempts
    teacher = auth_client(world.teacher)
    before = {row["id"] for row in teacher.get("/api/v1/results").json()["data"]}
    assert {test_id, real_id} <= before

    delete_attempts(ExamAttempt.objects.filter(pk=test_id))
    after = {row["id"] for row in teacher.get("/api/v1/results").json()["data"]}
    assert test_id not in after and real_id in after


def test_command_dry_run_lists_and_deletes_nothing(two_attempts):
    _, test_id, real_id, tester, _ = two_attempts
    out = StringIO()
    call_command("delete_attempts", "--student", tester.username, stdout=out)
    text = out.getvalue()
    assert test_id in text and real_id not in text
    assert "Hech narsa o'chirilmadi" in text
    assert ExamAttempt.objects.count() == 2


def test_command_deletes_only_matching_with_yes(two_attempts):
    world, _, real_id, tester, _ = two_attempts
    out = StringIO()
    call_command(
        "delete_attempts",
        "--student",
        tester.email,
        "--exam-title",
        world.exam.title[:5],
        "--yes",
        stdout=out,
    )
    assert "O'chirildi: 1" in out.getvalue()
    assert list(ExamAttempt.objects.values_list("pk", flat=True)) == [uuid.UUID(real_id)]


def test_command_requires_a_filter():
    with pytest.raises(CommandError, match="Kamida bitta filtr"):
        call_command("delete_attempts", "--yes")


def test_command_refuses_more_than_max(two_attempts):
    world, *_ = two_attempts
    with pytest.raises(CommandError, match="--max"):
        call_command(
            "delete_attempts", "--assignment", str(world.assignment.id), "--max", "1", "--yes"
        )
    assert ExamAttempt.objects.count() == 2


def test_command_rejects_bad_ids_and_dates():
    with pytest.raises(CommandError):
        call_command("delete_attempts", "--attempt", "not-a-uuid")
    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        call_command("delete_attempts", "--since", "27.11.2026")


def test_command_date_filter(two_attempts):
    out = StringIO()
    call_command("delete_attempts", "--since", "2099-01-01", stdout=out)
    assert "Mos attempt topilmadi" in out.getvalue()


# -------------------------------- attempts ----------------------------------
def test_deleted_attempts_stay_in_audit_log_forever(api, make_world):
    world = make_world(open_ended=False)
    client = api(world.student)
    attempt_id = client.start(world.assignment).json()["id"]
    client.answer(
        attempt_id, world.eq["single"], option_ids=[option_id(world.q["single"], "Right")]
    )
    client.submit(attempt_id)

    call_command("delete_attempts", "--attempt", attempt_id, "--yes", stdout=StringIO())

    (entry,) = AuditLog.objects.filter(action=AuditAction.ATTEMPTS_DELETED)
    assert str(entry.entity_id) == attempt_id and entry.actor is None
    meta = entry.metadata
    assert meta["student_username"] == world.student.username
    assert meta["exam_title"] == world.exam.title
    assert meta["status"] == "GRADED" and float(meta["score"]) == 2.0
    assert meta["submitted_at"]

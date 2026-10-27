from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.attempts.choices import AttemptStatus, FinalizationReason
from apps.attempts.models import ExamAttempt
from apps.attempts.services import finalize_expired_attempts, finalize_if_expired
from apps.attempts.tests.conftest import option_id
from apps.attempts.tests.factories import AttemptFactory

pytestmark = pytest.mark.django_db


def expire(attempt_id, seconds=120):
    ExamAttempt.objects.filter(pk=attempt_id).update(
        deadline_at=timezone.now() - timedelta(seconds=seconds)
    )


def started(api, world):
    client = api(world.student)
    return client, client.start(world.assignment).json()["id"]


def test_finalize_if_expired_grades_saved_answers_and_is_idempotent(api, world):
    client, attempt_id = started(api, world)
    client.answer(
        attempt_id, world.eq["single"], option_ids=[option_id(world.q["single"], "Right")]
    )
    expire(attempt_id)

    assert finalize_if_expired(attempt_id) is True
    attempt = ExamAttempt.objects.get(pk=attempt_id)
    assert attempt.status == AttemptStatus.GRADED
    assert attempt.score == 2
    assert attempt.submitted_at == attempt.deadline_at
    assert attempt.finalization_reason == FinalizationReason.TIMEOUT
    assert finalize_if_expired(attempt_id) is False


def test_attempt_inside_grace_is_not_finalized(api, world):
    _, attempt_id = started(api, world)
    expire(attempt_id, seconds=3)
    assert finalize_if_expired(attempt_id) is False
    assert ExamAttempt.objects.get(pk=attempt_id).status == AttemptStatus.IN_PROGRESS


def test_finalize_unknown_attempt_returns_false():
    assert finalize_if_expired("00000000-0000-4000-8000-000000000000") is False


def test_open_ended_text_in_expired_attempt_goes_to_manual_grading(api, world):
    client, attempt_id = started(api, world)
    client.answer(attempt_id, world.eq["open"], text_answer="written before the deadline")
    expire(attempt_id)
    finalize_if_expired(attempt_id)
    assert ExamAttempt.objects.get(pk=attempt_id).status == AttemptStatus.PENDING_GRADING


def test_retrieve_finalizes_expired_attempt(api, world):
    client, attempt_id = started(api, world)
    expire(attempt_id)
    body = client.detail(attempt_id).json()
    assert body["status"] in ("GRADED", "PENDING_GRADING")
    assert "questions" not in body  # endi faol emas -> faqat natija


def test_attempt_list_finalizes_expired_attempts(api, world):
    client, attempt_id = started(api, world)
    expire(attempt_id)
    rows = client.client.get("/api/v1/attempts").json()["data"]
    assert rows[0]["id"] == attempt_id
    assert rows[0]["status"] != "IN_PROGRESS"


def test_assignment_list_finalizes_so_can_start_is_accurate(api, make_world):
    world = make_world(max_attempts=1)
    client, attempt_id = started(api, world)
    expire(attempt_id)
    row = client.client.get("/api/v1/exam-assignments").json()["data"][0]
    assert row["active_attempt_id"] is None
    assert row["attempts_used"] == 1 and row["can_start"] is False


def test_management_command_closes_only_expired_attempts(api, world):
    from apps.users.tests.factories import StudentFactory

    other_students = [StudentFactory() for _ in range(2)]
    expired = [
        AttemptFactory(
            assignment=world.assignment,
            student=student,
            deadline_at=timezone.now() - timedelta(minutes=5),
        )
        for student in other_students
    ]
    fresh = AttemptFactory(assignment=world.assignment, student=world.student)

    out = StringIO()
    call_command("finalize_expired_attempts", stdout=out)
    assert "Yopilgan attemptlar: 2" in out.getvalue()
    for attempt in expired:
        attempt.refresh_from_db()
        assert attempt.status == AttemptStatus.GRADED
        assert attempt.submitted_at == attempt.deadline_at
    fresh.refresh_from_db()
    assert fresh.status == AttemptStatus.IN_PROGRESS

    again = StringIO()
    call_command("finalize_expired_attempts", stdout=again)
    assert "Yopilgan attemptlar: 0" in again.getvalue()


def test_finalize_expired_attempts_respects_queryset_and_limit(world):
    from apps.users.tests.factories import StudentFactory

    attempts = [
        AttemptFactory(
            assignment=world.assignment,
            student=StudentFactory(),
            deadline_at=timezone.now() - timedelta(minutes=5),
        )
        for _ in range(3)
    ]
    scoped = ExamAttempt.objects.filter(pk=attempts[0].pk)
    assert finalize_expired_attempts(scoped) == 1
    assert finalize_expired_attempts(limit=1) == 1
    assert finalize_expired_attempts() == 1
    assert finalize_expired_attempts() == 0

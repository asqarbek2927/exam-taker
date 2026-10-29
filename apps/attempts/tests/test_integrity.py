import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.attempts.choices import AttemptStatus, FinalizationReason
from apps.attempts.models import AttemptEvent, ExamAttempt
from apps.audit.choices import AuditAction
from apps.audit.models import AuditLog
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db


def post_event(client, attempt_id, event_type, *, event_id=None, details=None):
    return client.post(
        f"/api/v1/attempts/{attempt_id}/events",
        {
            "event_id": str(event_id or uuid.uuid4()),
            "type": event_type,
            "client_at": timezone.now().isoformat(),
            "details": details or {},
        },
        format="json",
    )


def test_event_is_idempotent_and_details_are_sanitized(auth_client, api, make_world):
    world = make_world(open_ended=False)
    attempt_id = api(world.student).start(world.assignment).json()["id"]
    client = auth_client(world.student)
    event_id = uuid.uuid4()

    first = post_event(
        client,
        attempt_id,
        "COPY",
        event_id=event_id,
        details={
            "visibility_state": "hidden",
            "correct_answer": "must-not-be-stored",
            "clipboard_text": "must-not-be-stored",
        },
    )
    retry = post_event(client, attempt_id, "COPY", event_id=event_id)

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert first.json()["focus_violations"] == 0
    assert first.json()["action"] == "WARN"
    event = AttemptEvent.objects.get(attempt_id=attempt_id)
    assert event.details == {"visibility_state": "hidden"}
    assert AuditLog.objects.filter(action=AuditAction.ATTEMPT_INTEGRITY_EVENT).count() == 1


def test_three_long_tab_hides_submit_with_focus_limit(auth_client, api, make_world):
    world = make_world(open_ended=False)
    attempt_id = api(world.student).start(world.assignment).json()["id"]
    client = auth_client(world.student)

    for violation in range(1, 4):
        AttemptEvent.objects.filter(attempt_id=attempt_id).update(
            received_at=timezone.now() - timedelta(seconds=10)
        )
        hidden_id = uuid.uuid4()
        hidden = post_event(client, attempt_id, "TAB_HIDDEN", event_id=hidden_id)
        assert hidden.status_code == 200
        AttemptEvent.objects.filter(event_id=hidden_id).update(
            received_at=timezone.now() - timedelta(seconds=3)
        )
        visible = post_event(client, attempt_id, "TAB_VISIBLE")
        assert visible.status_code == 200
        assert visible.json()["focus_violations"] == violation

    assert visible.json()["action"] == "SUBMIT"
    assert visible.json()["status"] == "GRADED"
    assert visible.json()["submission_reason"] == "FOCUS_LIMIT"
    attempt = ExamAttempt.objects.get(pk=attempt_id)
    assert attempt.focus_violations == 3
    assert attempt.finalization_reason == FinalizationReason.FOCUS_LIMIT
    assert attempt.status == AttemptStatus.GRADED

    assert post_event(client, attempt_id, "COPY").status_code == 409
    student_detail = client.get(f"/api/v1/attempts/{attempt_id}").json()
    assert "events" not in student_detail
    staff_detail = auth_client(world.teacher).get(f"/api/v1/attempts/{attempt_id}").json()
    assert len(staff_detail["events"]) == 6
    assert sum(event["counts_violation"] for event in staff_detail["events"]) == 3


def test_short_tab_hide_and_fullscreen_exit_do_not_count(auth_client, api, make_world):
    world = make_world(open_ended=False)
    attempt_id = api(world.student).start(world.assignment).json()["id"]
    client = auth_client(world.student)

    assert post_event(client, attempt_id, "TAB_HIDDEN").status_code == 200
    visible = post_event(client, attempt_id, "TAB_VISIBLE")
    fullscreen = post_event(client, attempt_id, "FULLSCREEN_EXIT")

    assert visible.json()["focus_violations"] == 0
    assert fullscreen.json()["focus_violations"] == 0
    assert fullscreen.json()["action"] == "WARN"
    assert ExamAttempt.objects.get(pk=attempt_id).status == AttemptStatus.IN_PROGRESS


def test_fullscreen_declined_submits_immediately(auth_client, api, make_world):
    world = make_world(open_ended=False)
    attempt_id = api(world.student).start(world.assignment).json()["id"]

    response = post_event(auth_client(world.student), attempt_id, "FULLSCREEN_DECLINED")

    assert response.status_code == 200
    assert response.json()["action"] == "SUBMIT"
    assert response.json()["submission_reason"] == "FULLSCREEN_DECLINED"
    attempt = ExamAttempt.objects.get(pk=attempt_id)
    assert attempt.finalization_reason == FinalizationReason.FULLSCREEN_DECLINED
    assert attempt.status == AttemptStatus.GRADED


def test_event_scope_and_validation(auth_client, api, make_world):
    world = make_world(open_ended=False)
    attempt_id = api(world.student).start(world.assignment).json()["id"]

    assert post_event(auth_client(StudentFactory()), attempt_id, "COPY").status_code == 404
    assert post_event(auth_client(world.teacher), attempt_id, "COPY").status_code == 403
    invalid = post_event(auth_client(world.student), attempt_id, "UNKNOWN")
    assert invalid.status_code == 422

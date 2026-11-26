from io import StringIO

import pytest
from django.core.management import call_command

from apps.attempts.management.commands.check_legacy_attempts import legacy_counts
from apps.attempts.models import ExamAttempt
from apps.attempts.tests.factories import AttemptFactory

pytestmark = pytest.mark.django_db


def test_reports_safe_when_all_attempts_use_snapshots(api, world):
    api(world.student).start(world.assignment)
    out = StringIO()
    call_command("check_legacy_attempts", stdout=out)
    assert all(value == 0 for value in legacy_counts().values())
    assert "xavfsiz." in out.getvalue()


def test_detects_legacy_attempt_and_changes_nothing():
    AttemptFactory()  # delivery_questions yo'q -> legacy
    before = list(ExamAttempt.objects.values())
    out = StringIO()
    call_command("check_legacy_attempts", stdout=out)
    assert legacy_counts()["attempts_without_snapshot"] == 1
    assert legacy_counts()["in_progress_attempts_without_snapshot"] == 1
    assert "XAVFSIZ EMAS" in out.getvalue()
    assert list(ExamAttempt.objects.values()) == before

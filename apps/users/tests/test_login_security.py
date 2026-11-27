"""Login xavfsizligi: timing orqali username aniqlanmaydi, xato urinishlar loglanadi."""

import logging
import time

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db
LOGIN = "/api/v1/auth/login"
ARGON2 = ["django.contrib.auth.hashers.Argon2PasswordHasher"]


def _avg_ms(client, identifier, runs=6):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        client.post(
            LOGIN, {"username_or_email": identifier, "password": "Wrong-Pass1"}, format="json"
        )
        times.append(time.perf_counter() - start)
    times = sorted(times)[1:-1]  # eng tez/sekinni tashlaymiz
    return sum(times) / len(times) * 1000


@override_settings(PASSWORD_HASHERS=ARGON2)
def test_missing_user_takes_as_long_as_existing_user():
    """Oldin: mavjud user ~80 ms, mavjud bo‘lmagan ~2 ms — username'larni aniqlash mumkin edi."""
    user = StudentFactory()
    client = APIClient()
    existing = _avg_ms(client, user.username)
    missing = _avg_ms(client, "no_such_user_xyz")
    assert missing > existing * 0.5, (existing, missing)


@override_settings(PASSWORD_HASHERS=ARGON2)
def test_inactive_user_is_not_faster_either():
    user = StudentFactory()
    user.status = UserStatus.INACTIVE
    user.save(update_fields=["status"])
    active = StudentFactory()
    client = APIClient()
    assert _avg_ms(client, user.username) > _avg_ms(client, active.username) * 0.5


def test_failed_login_is_logged_without_password(caplog):
    user = StudentFactory()
    with caplog.at_level(logging.WARNING, logger="examtaker.security"):
        APIClient(REMOTE_ADDR="10.1.2.3").post(
            LOGIN, {"username_or_email": user.username, "password": "Wrong-Pass1"}, format="json"
        )
    record = next(r for r in caplog.records if r.name == "examtaker.security")
    message = record.getMessage()
    assert "login_failed" in message and user.username in message and "10.1.2.3" in message
    assert "Wrong-Pass1" not in message

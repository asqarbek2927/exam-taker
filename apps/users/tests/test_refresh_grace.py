"""Refresh token grace oynasi va refresh throttling.

Muammo (prod): access token 30 daqiqada tugaganda front bir nechta parallel so‘rov
uchun bir xil refresh token bilan bir vaqtda refresh qiladi. Rotation tufayli
ikkinchi refresh 401 olardi va studentni imtihon o‘rtasida login sahifasiga yuborardi.
"""

import threading

import pytest
from django.core.cache import cache
from django.db import connection, connections
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.users.choices import UserStatus
from apps.users.services import revoke_all_tokens
from apps.users.tests.factories import DEFAULT_PASSWORD, StudentFactory
from common.throttling import RefreshIPRateThrottle, RefreshUserRateThrottle

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


def _login(client, user) -> dict:
    response = client.post(
        LOGIN, {"username_or_email": user.username, "password": DEFAULT_PASSWORD}, format="json"
    )
    assert response.status_code == 200, response.content
    return response.json()


def _refresh(token, client=None):
    return (client or APIClient()).post(REFRESH, {"refresh_token": token}, format="json")


# ------------------------------- grace oynasi -------------------------------
def test_parallel_refresh_with_same_token_all_succeed_with_same_pair(student):
    """Front 5 ta so‘rov uchun 5 marta refresh qilsa ham — logout bo‘lmaydi."""
    refresh = _login(APIClient(), student)["refresh_token"]
    outstanding_before = OutstandingToken.objects.count()

    responses = [_refresh(refresh) for _ in range(5)]

    assert [r.status_code for r in responses] == [200] * 5
    bodies = [r.json() for r in responses]
    assert all(body == bodies[0] for body in bodies), "Hammasi bir xil juftlikni olishi kerak"
    assert bodies[0]["refresh_token"] != refresh
    # Takroriy so‘rovlar yangi session yaratmaydi.
    assert OutstandingToken.objects.count() == outstanding_before + 1


def test_new_refresh_token_from_grace_keeps_working(student):
    refresh = _login(APIClient(), student)["refresh_token"]
    first = _refresh(refresh).json()
    _refresh(refresh)  # parallel takror
    nxt = _refresh(first["refresh_token"])
    assert nxt.status_code == 200
    assert nxt.json()["refresh_token"] not in {refresh, first["refresh_token"]}


def test_old_token_rejected_after_grace_window(student):
    refresh = _login(APIClient(), student)["refresh_token"]
    assert _refresh(refresh).status_code == 200
    cache.clear()  # grace oynasi tugadi (cache TTL)
    assert _refresh(refresh).status_code == 401


@override_settings(JWT_REFRESH_GRACE_SECONDS=0)
def test_grace_can_be_disabled(student):
    refresh = _login(APIClient(), student)["refresh_token"]
    assert _refresh(refresh).status_code == 200
    assert _refresh(refresh).status_code == 401


def test_logged_out_token_gets_no_grace(student):
    client = APIClient()
    tokens = _login(client, student)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    assert (
        client.post(LOGOUT, {"refresh_token": tokens["refresh_token"]}, format="json").status_code
        == 204
    )
    assert _refresh(tokens["refresh_token"]).status_code == 401


def test_grace_denied_when_new_token_was_logged_out(student):
    refresh = _login(APIClient(), student)["refresh_token"]
    new_pair = _refresh(refresh).json()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_pair['access_token']}")
    assert (
        client.post(LOGOUT, {"refresh_token": new_pair["refresh_token"]}, format="json").status_code
        == 204
    )
    assert _refresh(refresh).status_code == 401


def test_grace_denied_after_all_sessions_revoked(student):
    """Parol almashtirish / admin status o‘zgartirishi barcha sessionlarni bekor qiladi."""
    refresh = _login(APIClient(), student)["refresh_token"]
    assert _refresh(refresh).status_code == 200
    revoke_all_tokens(student)
    assert _refresh(refresh).status_code == 401


def test_grace_denied_for_inactive_user(student):
    refresh = _login(APIClient(), student)["refresh_token"]
    assert _refresh(refresh).status_code == 200
    student.status = UserStatus.INACTIVE
    student.save(update_fields=["status"])
    assert _refresh(refresh).status_code == 401


def test_tampered_or_wrong_type_tokens_rejected(student):
    tokens = _login(APIClient(), student)
    header, body, signature = tokens["refresh_token"].split(".")
    tampered = f"{header}.{body}.{signature[:-2]}xx"
    assert _refresh(tampered).status_code == 401
    assert _refresh(tokens["access_token"]).status_code == 401  # access token refresh emas
    assert _refresh("garbage").status_code == 401


def test_refresh_response_contract_unchanged(student):
    refresh = _login(APIClient(), student)["refresh_token"]
    first, again = _refresh(refresh).json(), _refresh(refresh).json()
    assert set(first) == set(again) == {"access_token", "refresh_token"}


# ------------------------------- throttling ---------------------------------
@pytest.fixture
def prod_refresh_rates(monkeypatch):
    rates = {"refresh": "30/min", "refresh_ip": "1000/min"}
    monkeypatch.setattr(RefreshUserRateThrottle, "THROTTLE_RATES", rates)
    monkeypatch.setattr(RefreshIPRateThrottle, "THROTTLE_RATES", rates)


def test_classroom_behind_one_nat_ip_is_not_throttled(prod_refresh_rates):
    """60 student bitta IP dan, har biri 3 tadan parallel refresh — hech kim 429 olmaydi."""
    tokens = [_login(APIClient(), StudentFactory())["refresh_token"] for _ in range(60)]
    cache.clear()
    codes = [
        _refresh(token, APIClient(REMOTE_ADDR="10.0.0.1")).status_code
        for token in tokens
        for _ in range(3)
    ]
    assert codes.count(200) == 180


def test_refresh_is_limited_per_user(prod_refresh_rates, student):
    refresh = _login(APIClient(), student)["refresh_token"]
    cache.clear()
    codes = [_refresh(refresh).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429


# ------------------------- haqiqiy parallel (Postgres) -----------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Row lock faqat PostgreSQL da")
def test_truly_concurrent_refreshes_all_succeed():
    student = StudentFactory()
    refresh = _login(APIClient(), student)["refresh_token"]
    threads_count = 6
    barrier = threading.Barrier(threads_count)
    results: list = []

    def target():
        try:
            barrier.wait()
            response = _refresh(refresh)
            results.append((response.status_code, response.json().get("refresh_token")))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=target) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [code for code, _ in results] == [200] * threads_count
    assert len({token for _, token in results}) == 1

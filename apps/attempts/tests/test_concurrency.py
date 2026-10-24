"""Parallel so‘rovlar (faqat PostgreSQL: SQLite da `SELECT ... FOR UPDATE` yo‘q)."""

import threading

import pytest
from django.db import connection, connections
from rest_framework.test import APIClient

from apps.attempts.models import ExamAttempt

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Row-level lock faqat PostgreSQL da tekshiriladi"
    ),
]

THREADS = 6


def run_in_parallel(worker) -> list:
    results: list = []
    barrier = threading.Barrier(THREADS)

    def target():
        try:
            barrier.wait()
            results.append(worker())
        finally:
            connections.close_all()

    threads = [threading.Thread(target=target) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_parallel_start_creates_exactly_one_attempt(make_world):
    world = make_world(max_attempts=None)
    url = f"/api/v1/exam-assignments/{world.assignment.id}/start"

    def worker():
        client = APIClient()
        client.force_authenticate(world.student)
        return client.post(url).status_code

    codes = run_in_parallel(worker)
    assert sorted(codes) == [201] + [409] * (THREADS - 1)
    assert ExamAttempt.objects.filter(student=world.student).count() == 1


def test_parallel_start_never_exceeds_the_attempt_limit(make_world):
    world = make_world(max_attempts=1)
    url = f"/api/v1/exam-assignments/{world.assignment.id}/start"

    def worker():
        client = APIClient()
        client.force_authenticate(world.student)
        return client.post(url).status_code

    codes = run_in_parallel(worker)
    assert codes.count(201) == 1
    assert ExamAttempt.objects.filter(student=world.student).count() == 1


def test_parallel_submit_finalizes_once(make_world):
    world = make_world(open_ended=False)
    client = APIClient()
    client.force_authenticate(world.student)
    attempt_id = client.post(f"/api/v1/exam-assignments/{world.assignment.id}/start").json()["id"]

    def worker():
        own = APIClient()
        own.force_authenticate(world.student)
        return own.post(f"/api/v1/attempts/{attempt_id}/submit").status_code

    codes = run_in_parallel(worker)
    assert codes.count(200) == 1
    assert codes.count(409) == THREADS - 1

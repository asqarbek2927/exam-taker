import pytest
from django.core.cache import cache

pytestmark = pytest.mark.django_db


def test_liveness_is_public(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database_and_cache(client):
    cache.clear()
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert cache.get("health:ready") == "ok"

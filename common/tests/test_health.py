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


def test_django_admin_path_is_configurable(client, settings):
    """`DJANGO_ADMIN_URL` bo'yicha admin boshqa yo'lga ko'chadi yoki butunlay o'chadi."""
    import importlib

    from django.urls import clear_url_caches

    import config.urls

    try:
        settings.DJANGO_ADMIN_URL = "panel-x7k/"
        clear_url_caches()
        importlib.reload(config.urls)
        assert client.get("/panel-x7k/").status_code == 302  # login sahifasiga
        assert client.get("/admin/").status_code == 404

        settings.DJANGO_ADMIN_URL = ""
        clear_url_caches()
        importlib.reload(config.urls)
        assert client.get("/admin/").status_code == 404
    finally:
        settings.DJANGO_ADMIN_URL = "admin/"
        clear_url_caches()
        importlib.reload(config.urls)

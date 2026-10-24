import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttling holati testlar o‘rtasida aralashib ketmasligi uchun."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def admin(db):
    from apps.users.tests.factories import AdminFactory

    return AdminFactory()


@pytest.fixture
def teacher(db):
    from apps.users.tests.factories import TeacherFactory

    return TeacherFactory()


@pytest.fixture
def student(db):
    from apps.users.tests.factories import StudentFactory

    return StudentFactory()


@pytest.fixture
def auth_client(api_client):
    """`auth_client(user)` — foydalanuvchi sifatida autentifikatsiya qilingan client."""

    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make

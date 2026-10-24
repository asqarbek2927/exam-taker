import pytest

from apps.users.choices import UserRole, UserStatus
from apps.users.models import User
from apps.users.tests.factories import DEFAULT_PASSWORD, TeacherFactory

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_hashes_password():
    user = User.objects.create_user(
        email="  Teacher@Example.COM ",
        password=DEFAULT_PASSWORD,
        full_name="Aziz",
        role=UserRole.TEACHER,
    )
    assert user.email == "teacher@example.com"
    assert user.password != DEFAULT_PASSWORD
    assert user.check_password(DEFAULT_PASSWORD)
    assert user.status == UserStatus.ACTIVE
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False


def test_create_user_requires_valid_role():
    with pytest.raises(ValueError):
        User.objects.create_user(email="a@example.com", password="x", full_name="A")
    with pytest.raises(ValueError):
        User.objects.create_user(email="a@example.com", password="x", full_name="A", role="BOSS")


def test_create_superuser_sets_super_admin_role():
    user = User.objects.create_superuser(
        email="root@example.com", password=DEFAULT_PASSWORD, full_name="Root"
    )
    assert user.role == UserRole.SUPER_ADMIN
    assert user.is_staff is True
    assert user.is_superuser is True


def test_is_active_derives_from_status():
    user = TeacherFactory()
    user.status = UserStatus.INACTIVE
    user.save(update_fields=["status"])
    user.refresh_from_db()
    assert user.is_active is False


def test_get_by_natural_key_is_case_insensitive():
    user = TeacherFactory(email="mixed@example.com")
    assert User.objects.get_by_natural_key("MIXED@Example.com") == user

import pytest

from apps.users.choices import UserRole, UserStatus
from apps.users.models import User
from apps.users.tests.factories import DEFAULT_PASSWORD, TeacherFactory

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_hashes_password():
    user = User.objects.create_user(
        username="aziz_teacher",
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
        User.objects.create_user(
            username="user_a", email="a@example.com", password="x", full_name="A"
        )
    with pytest.raises(ValueError):
        User.objects.create_user(
            username="user_a",
            email="a@example.com",
            password="x",
            full_name="A",
            role="BOSS",
        )


def test_create_superuser_sets_super_admin_role():
    user = User.objects.create_superuser(
        username="root", email="root@example.com", password=DEFAULT_PASSWORD, full_name="Root"
    )
    assert user.role == UserRole.SUPER_ADMIN
    assert user.is_staff is True
    assert user.is_superuser is True


def test_create_superuser_without_email():
    user = User.objects.create_superuser(
        username="root_admin",
        password=DEFAULT_PASSWORD,
        full_name="Root Admin",
    )
    assert user.email is None
    assert user.username == "root_admin"
    assert user.role == UserRole.SUPER_ADMIN


def test_multiple_users_can_be_created_without_email_when_usernames_are_unique():
    first = User.objects.create_user(
        username="aziz_teacher",
        password=DEFAULT_PASSWORD,
        full_name="Aziz Rahimov",
        role=UserRole.TEACHER,
    )
    second = User.objects.create_user(
        username="aziz_student",
        password=DEFAULT_PASSWORD,
        full_name="Aziz Rahimov",
        role=UserRole.STUDENT,
    )

    assert first.email is None
    assert second.email is None
    assert first.username == "aziz_teacher"
    assert second.username == "aziz_student"


@pytest.mark.parametrize("username", [None, "", "   "])
def test_create_user_requires_username(username):
    with pytest.raises(ValueError, match="username majburiy"):
        User.objects.create_user(
            username=username,
            password=DEFAULT_PASSWORD,
            full_name="Aziz Rahimov",
            role=UserRole.TEACHER,
        )


def test_is_active_derives_from_status():
    user = TeacherFactory()
    user.status = UserStatus.INACTIVE
    user.save(update_fields=["status"])
    user.refresh_from_db()
    assert user.is_active is False


def test_get_by_natural_key_is_case_insensitive():
    user = TeacherFactory(username="mixed_user")
    assert User.objects.get_by_natural_key("MIXED_USER") == user

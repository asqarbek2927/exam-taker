from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.academics.choices import CourseTeacherType
from apps.academics.tests.factories import CourseTeacherFactory
from apps.users.tests.factories import (
    DEFAULT_PASSWORD,
    AdminFactory,
    StudentFactory,
    TeacherFactory,
)

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
PROFILE = "/api/v1/profile"
PHOTO = "/api/v1/profile/photo"
PASSWORD = "/api/v1/profile/change-password"
PREFERENCES = "/api/v1/profile/preferences"


def login(client, identifier, password=DEFAULT_PASSWORD):
    return client.post(
        LOGIN,
        {"email_or_username": identifier, "password": password},
        format="json",
    )


def authenticate(client, user):
    access = login(client, user.email).json()["access_token"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


def image_file(name="avatar.png", content_type="image/png"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color="red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def test_login_accepts_username_and_returns_must_change_password(api_client):
    user = TeacherFactory(must_change_password=True)
    response = api_client.post(
        LOGIN,
        {"emailOrUsername": user.username, "password": DEFAULT_PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


def test_login_rejects_expired_temporary_password(api_client):
    user = TeacherFactory(
        must_change_password=True,
        temporary_password_expires_at=timezone.now() - timedelta(seconds=1),
    )
    response = login(api_client, user.email)
    assert response.status_code == 401
    assert "muddati tugagan" in response.json()["message"]


def test_refresh_rejects_expired_temporary_password(api_client):
    user = TeacherFactory(
        must_change_password=True,
        temporary_password_expires_at=timezone.now() + timedelta(seconds=30),
    )
    refresh = login(api_client, user.email).json()["refresh_token"]
    user.temporary_password_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["temporary_password_expires_at"])
    response = api_client.post("/api/v1/auth/refresh", {"refresh_token": refresh}, format="json")
    assert response.status_code == 401
    assert "muddati tugagan" in response.json()["message"]


def test_me_returns_permissions_and_nested_preferences(api_client):
    assignment = CourseTeacherFactory(type=CourseTeacherType.SUPPORT)
    authenticate(api_client, assignment.teacher)

    body = api_client.get(ME).json()
    assert body["permissions"] == {
        "can_create_question": True,
        "can_create_exam": True,
        "can_assign_exam": True,
        "can_grade": True,
        "is_support_teacher": True,
    }
    assert body["preferences"] == {"language": "en", "theme": "system"}
    assert "password" not in body


def test_profile_role_rules(api_client):
    student = StudentFactory()
    authenticate(api_client, student)
    rejected = api_client.patch(PROFILE, {"full_name": "Changed"}, format="json")
    assert rejected.status_code == 422
    assert "full_name" in rejected.json()["errors"]

    admin = AdminFactory()
    authenticate(api_client, admin)
    accepted = api_client.patch(
        PROFILE, {"full_name": "New Admin", "phone_number": "+998901234567"}, format="json"
    )
    assert accepted.status_code == 200
    assert accepted.json()["full_name"] == "New Admin"


def test_preferences_updates_language_and_theme(api_client):
    user = TeacherFactory()
    authenticate(api_client, user)
    response = api_client.patch(PREFERENCES, {"language": "ru", "theme": "dark"}, format="json")
    assert response.status_code == 200
    assert response.json() == {"language": "ru", "theme": "dark"}


def test_photo_upload_and_delete(
    api_client, teacher, tmp_path, settings, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = tmp_path
    authenticate(api_client, teacher)
    uploaded = api_client.post(PHOTO, {"image": image_file()}, format="multipart")
    assert uploaded.status_code == 200
    assert uploaded.json()["avatar_url"].endswith(".png")
    teacher.refresh_from_db()
    stored_path = tmp_path / teacher.avatar.name
    assert stored_path.exists()

    with django_capture_on_commit_callbacks(execute=True):
        deleted = api_client.delete(PHOTO)
    assert deleted.status_code == 204
    teacher.refresh_from_db()
    assert not teacher.avatar
    assert not stored_path.exists()


def test_photo_rejects_non_image(api_client, teacher):
    authenticate(api_client, teacher)
    bad = SimpleUploadedFile("avatar.png", b"not-an-image", content_type="image/png")
    response = api_client.post(PHOTO, {"image": bad}, format="multipart")
    assert response.status_code == 422
    assert "image" in response.json()["errors"]


def test_change_password_without_confirmation_clears_temporary_flag(api_client):
    user = TeacherFactory(
        must_change_password=True,
        temporary_password_expires_at=timezone.now() + timedelta(hours=1),
    )
    authenticate(api_client, user)
    new_password = "An0ther-Str0ng-Pass!"
    response = api_client.post(
        PASSWORD,
        {"current_password": DEFAULT_PASSWORD, "new_password": new_password},
        format="json",
    )
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.temporary_password_expires_at is None
    assert login(api_client, user.username, new_password).status_code == 200

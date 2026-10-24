import pytest
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.users.choices import UserRole, UserStatus
from apps.users.models import User
from apps.users.tests.factories import (
    DEFAULT_PASSWORD,
    StudentFactory,
    TeacherFactory,
)

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users"


def payload(**overrides):
    data = {
        "full_name": "Yangi Teacher",
        "email": "New.Teacher@Example.com",
        "password": DEFAULT_PASSWORD,
        "role": "TEACHER",
    }
    data.update(overrides)
    return data


# --- permissions ---------------------------------------------------------
@pytest.mark.parametrize("role_fixture", ["teacher", "student"])
def test_non_admin_cannot_access_users(request, auth_client, role_fixture):
    client = auth_client(request.getfixturevalue(role_fixture))
    assert client.get(USERS).status_code == 403
    assert client.post(USERS, payload(), format="json").status_code == 403


def test_anonymous_gets_401(api_client):
    assert api_client.get(USERS).status_code == 401


# --- create --------------------------------------------------------------
def test_admin_creates_teacher(auth_client, admin):
    response = auth_client(admin).post(USERS, payload(), format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.teacher@example.com"
    assert body["role"] == "TEACHER"
    assert body["status"] == "ACTIVE"
    assert "password" not in body
    assert User.objects.get(pk=body["id"]).check_password(DEFAULT_PASSWORD)


def test_admin_creates_student(auth_client, admin):
    response = auth_client(admin).post(
        USERS, payload(role="STUDENT", email="s@example.com"), format="json"
    )
    assert response.status_code == 201
    assert response.json()["role"] == "STUDENT"


def test_cannot_create_super_admin_via_api(auth_client, admin):
    response = auth_client(admin).post(USERS, payload(role="SUPER_ADMIN"), format="json")
    assert response.status_code == 422
    assert "role" in response.json()["errors"]


def test_duplicate_email_is_rejected_case_insensitively(auth_client, admin, teacher):
    response = auth_client(admin).post(USERS, payload(email=teacher.email.upper()), format="json")
    assert response.status_code == 422
    assert "email" in response.json()["errors"]


def test_weak_password_is_rejected(auth_client, admin):
    response = auth_client(admin).post(USERS, payload(password="12345678"), format="json")
    assert response.status_code == 422
    assert (
        "non_field_errors" in response.json()["errors"] or "password" in response.json()["errors"]
    )
    assert not User.objects.filter(email="new.teacher@example.com").exists()


# --- list / filters / pagination ----------------------------------------
def test_list_uses_pagination_contract(auth_client, admin):
    TeacherFactory.create_batch(3)
    response = auth_client(admin).get(USERS, {"limit": 2, "page": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"] == {"page": 1, "limit": 2, "total": 4, "total_pages": 2}


def test_list_filters_by_role_status_and_search(auth_client, admin):
    TeacherFactory(full_name="Zoir Karimov")
    StudentFactory(full_name="Dilnoza Aliyeva")
    StudentFactory(full_name="Inactive One", status=UserStatus.INACTIVE)
    client = auth_client(admin)

    students = client.get(USERS, {"role": "STUDENT"}).json()["data"]
    assert {u["role"] for u in students} == {"STUDENT"}
    assert len(students) == 2

    inactive = client.get(USERS, {"status": "INACTIVE"}).json()["data"]
    assert [u["full_name"] for u in inactive] == ["Inactive One"]

    found = client.get(USERS, {"search": "zoir"}).json()["data"]
    assert [u["full_name"] for u in found] == ["Zoir Karimov"]


def test_invalid_filter_value_returns_422(auth_client, admin):
    response = auth_client(admin).get(USERS, {"role": "BOSS"})
    assert response.status_code == 422


def test_non_uuid_id_returns_404_in_error_format(auth_client, admin):
    response = auth_client(admin).get(f"{USERS}/not-a-uuid")
    assert response.status_code == 404
    assert response.json() == {
        "status_code": 404,
        "error": "Not Found",
        "message": "Resurs topilmadi.",
    }


# --- retrieve / update ---------------------------------------------------
def test_retrieve_and_update(auth_client, admin, teacher):
    client = auth_client(admin)
    assert client.get(f"{USERS}/{teacher.id}").json()["email"] == teacher.email

    response = client.patch(
        f"{USERS}/{teacher.id}",
        {"full_name": "Yangi Ism", "email": "CHANGED@example.com"},
        format="json",
    )
    assert response.status_code == 200
    teacher.refresh_from_db()
    assert teacher.full_name == "Yangi Ism"
    assert teacher.email == "changed@example.com"


def test_update_cannot_change_role_or_status(auth_client, admin, teacher):
    auth_client(admin).patch(
        f"{USERS}/{teacher.id}", {"role": "SUPER_ADMIN", "status": "INACTIVE"}, format="json"
    )
    teacher.refresh_from_db()
    assert teacher.role == UserRole.TEACHER
    assert teacher.status == UserStatus.ACTIVE


def test_update_email_conflict_returns_422(auth_client, admin, teacher):
    other = TeacherFactory()
    response = auth_client(admin).patch(
        f"{USERS}/{teacher.id}", {"email": other.email}, format="json"
    )
    assert response.status_code == 422


def test_delete_is_not_allowed(auth_client, admin, teacher):
    assert auth_client(admin).delete(f"{USERS}/{teacher.id}").status_code == 405


# --- activate / deactivate / set-password -------------------------------
def test_deactivate_and_activate(auth_client, admin, teacher):
    client = auth_client(admin)
    response = client.post(f"{USERS}/{teacher.id}/deactivate")
    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"

    response = client.post(f"{USERS}/{teacher.id}/activate")
    assert response.json()["status"] == "ACTIVE"


def test_admin_cannot_deactivate_self(auth_client, admin):
    response = auth_client(admin).post(f"{USERS}/{admin.id}/deactivate")
    assert response.status_code == 400
    admin.refresh_from_db()
    assert admin.is_active


def test_deactivate_revokes_refresh_tokens(api_client, auth_client, admin, teacher):
    login = api_client.post(
        "/api/v1/auth/login",
        {"email": teacher.email, "password": DEFAULT_PASSWORD},
        format="json",
    ).json()
    assert OutstandingToken.objects.filter(user=teacher).count() == 1

    auth_client(admin).post(f"{USERS}/{teacher.id}/deactivate")
    assert BlacklistedToken.objects.filter(token__user=teacher).count() == 1

    refresh = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": login["refresh_token"]}, format="json"
    )
    assert refresh.status_code == 401


def test_set_password(api_client, auth_client, admin, teacher):
    new_password = "An0ther-Str0ng-Pass!"
    response = auth_client(admin).post(
        f"{USERS}/{teacher.id}/set-password", {"password": new_password}, format="json"
    )
    assert response.status_code == 204

    ok = api_client.post(
        "/api/v1/auth/login", {"email": teacher.email, "password": new_password}, format="json"
    )
    assert ok.status_code == 200
    old = api_client.post(
        "/api/v1/auth/login",
        {"email": teacher.email, "password": DEFAULT_PASSWORD},
        format="json",
    )
    assert old.status_code == 401


def test_set_password_rejects_weak_password(auth_client, admin, teacher):
    response = auth_client(admin).post(
        f"{USERS}/{teacher.id}/set-password", {"password": "short"}, format="json"
    )
    assert response.status_code == 422


# --- /teachers, /students -----------------------------------------------
def test_teachers_and_students_endpoints_are_role_scoped(auth_client, admin):
    t = TeacherFactory()
    s = StudentFactory()
    client = auth_client(admin)

    teachers = client.get("/api/v1/teachers").json()["data"]
    students = client.get("/api/v1/students").json()["data"]
    assert [u["id"] for u in teachers] == [str(t.id)]
    assert [u["id"] for u in students] == [str(s.id)]

    # Teacher id si /students orqali topilmaydi.
    assert client.get(f"/api/v1/students/{t.id}").status_code == 404


def test_teachers_endpoint_forbidden_for_non_admin(auth_client, teacher):
    assert auth_client(teacher).get("/api/v1/teachers").status_code == 403

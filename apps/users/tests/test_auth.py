import pytest
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.users.choices import UserStatus
from apps.users.tests.factories import DEFAULT_PASSWORD, TeacherFactory

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
CHANGE_PASSWORD = "/api/v1/auth/change-password"


def login(client, user, password=DEFAULT_PASSWORD):
    return client.post(LOGIN, {"email": user.email, "password": password}, format="json")


def bearer(client, access):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


def test_login_success_returns_user_and_tokens(api_client, teacher):
    response = login(api_client, teacher)
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {
        "id": str(teacher.id),
        "full_name": teacher.full_name,
        "email": teacher.email,
        "role": "TEACHER",
    }
    assert body["access_token"] and body["refresh_token"]


def test_login_email_is_case_insensitive(api_client, teacher):
    response = api_client.post(
        LOGIN, {"email": teacher.email.upper(), "password": DEFAULT_PASSWORD}, format="json"
    )
    assert response.status_code == 200


def test_login_wrong_password_returns_401_in_error_format(api_client, teacher):
    response = login(api_client, teacher, password="wrong-password")
    assert response.status_code == 401
    assert response.json() == {
        "status_code": 401,
        "error": "Unauthorized",
        "message": "Email yoki parol noto‘g‘ri, yoki akkaunt faol emas.",
    }


def test_login_inactive_user_is_rejected(api_client):
    user = TeacherFactory(status=UserStatus.INACTIVE)
    assert login(api_client, user).status_code == 401


def test_login_missing_fields_returns_422(api_client):
    response = api_client.post(LOGIN, {}, format="json")
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "Validation failed"
    assert set(body["errors"]) == {"email", "password"}


def test_login_is_throttled_per_ip_and_email(api_client, teacher, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "login", "2/min")
    assert login(api_client, teacher, password="bad").status_code == 401
    assert login(api_client, teacher, password="bad").status_code == 401
    response = login(api_client, teacher, password="bad")
    assert response.status_code == 429
    assert response.json()["status_code"] == 429
    assert "soniyadan keyin" in response.json()["message"]


def test_login_throttle_does_not_block_other_accounts_on_same_ip(api_client, monkeypatch):
    """Bitta NAT IP dan ko‘p student kirsa, bir-birini bloklamasligi kerak."""
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "login", "2/min")
    students = [TeacherFactory() for _ in range(5)]
    for user in students:
        assert login(api_client, user).status_code == 200


def test_login_ip_throttle_blocks_mass_attempts(api_client, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "login_ip", "3/min")
    codes = [
        api_client.post(
            LOGIN, {"email": f"nobody{i}@example.com", "password": "x"}, format="json"
        ).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, 429, 429]


def test_me_requires_authentication(api_client):
    response = api_client.get(ME)
    assert response.status_code == 401
    assert response.json() == {
        "status_code": 401,
        "error": "Unauthorized",
        "message": "Autentifikatsiya talab qilinadi.",
    }


def test_me_returns_current_user(api_client, teacher):
    bearer(api_client, login(api_client, teacher).json()["access_token"])
    response = api_client.get(ME)
    assert response.status_code == 200
    assert response.json()["email"] == teacher.email
    assert "password" not in response.json()


def test_me_updates_language_preference(api_client, teacher):
    bearer(api_client, login(api_client, teacher).json()["access_token"])

    response = api_client.patch(ME, {"language": "uz"}, format="json")
    assert response.status_code == 200
    assert response.json()["language"] == "uz"
    teacher.refresh_from_db()
    assert teacher.language == "uz"

    invalid = api_client.patch(ME, {"language": "de"}, format="json")
    assert invalid.status_code == 422
    assert "language" in invalid.json()["errors"]


def test_me_updates_profile_but_keeps_managed_fields_read_only(api_client, teacher):
    bearer(api_client, login(api_client, teacher).json()["access_token"])

    response = api_client.patch(
        ME,
        {
            "full_name": "Updated Teacher",
            "phone_number": "+998 90 123 45 67",
            "avatar_url": None,
            "email": "hacker@example.com",
            "role": "SUPER_ADMIN",
            "status": "INACTIVE",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Updated Teacher"
    assert response.json()["phone_number"] == "+998 90 123 45 67"
    assert response.json()["avatar_url"] == ""
    teacher.refresh_from_db()
    assert teacher.email != "hacker@example.com"
    assert teacher.role == "TEACHER"
    assert teacher.status == "ACTIVE"


@pytest.mark.parametrize("phone_number", ["123", "not-a-phone", "+998 abc"])
def test_me_rejects_invalid_phone(api_client, teacher, phone_number):
    bearer(api_client, login(api_client, teacher).json()["access_token"])
    response = api_client.patch(ME, {"phone_number": phone_number}, format="json")
    assert response.status_code == 422
    assert "phone_number" in response.json()["errors"]


def test_change_own_password_requires_current_password(api_client, teacher):
    bearer(api_client, login(api_client, teacher).json()["access_token"])
    new_password = "An0ther-Str0ng-Pass!"

    wrong = api_client.post(
        CHANGE_PASSWORD,
        {
            "current_password": "wrong-password",
            "new_password": new_password,
            "confirm_new_password": new_password,
        },
        format="json",
    )
    assert wrong.status_code == 422
    assert "current_password" in wrong.json()["errors"]

    changed = api_client.post(
        CHANGE_PASSWORD,
        {
            "current_password": DEFAULT_PASSWORD,
            "new_password": new_password,
            "confirm_new_password": new_password,
        },
        format="json",
    )
    assert changed.status_code == 204
    assert login(api_client, teacher, password=DEFAULT_PASSWORD).status_code == 401
    assert login(api_client, teacher, password=new_password).status_code == 200


@pytest.mark.parametrize(
    "new_password,confirm_new_password",
    [
        ("An0ther-Str0ng-Pass!", "Different-Str0ng-Pass!"),
        ("short", "short"),
        ("lowercase-password1!", "lowercase-password1!"),
        ("UPPERCASE-PASSWORD1!", "UPPERCASE-PASSWORD1!"),
        ("No-Numbers-Here!", "No-Numbers-Here!"),
    ],
)
def test_change_own_password_validates_confirmation_and_strength(
    api_client, teacher, new_password, confirm_new_password
):
    bearer(api_client, login(api_client, teacher).json()["access_token"])
    response = api_client.post(
        CHANGE_PASSWORD,
        {
            "current_password": DEFAULT_PASSWORD,
            "new_password": new_password,
            "confirm_new_password": confirm_new_password,
        },
        format="json",
    )
    assert response.status_code == 422


def test_me_with_invalid_token_returns_401(api_client):
    bearer(api_client, "not-a-token")
    response = api_client.get(ME)
    assert response.status_code == 401
    assert response.json()["message"] == "Token yaroqsiz yoki muddati tugagan."


def test_access_token_of_deactivated_user_stops_working(api_client, teacher):
    access = login(api_client, teacher).json()["access_token"]
    teacher.status = UserStatus.INACTIVE
    teacher.save(update_fields=["status"])
    bearer(api_client, access)
    assert api_client.get(ME).status_code == 401


def test_refresh_rotates_and_blacklists_old_token(api_client, teacher):
    old_refresh = login(api_client, teacher).json()["refresh_token"]

    response = api_client.post(REFRESH, {"refresh_token": old_refresh}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"] and body["refresh_token"] != old_refresh

    # Eski refresh token qayta ishlatib bo‘lmaydi.
    reuse = api_client.post(REFRESH, {"refresh_token": old_refresh}, format="json")
    assert reuse.status_code == 401


def test_refresh_with_garbage_token_returns_401(api_client):
    response = api_client.post(REFRESH, {"refresh_token": "garbage"}, format="json")
    assert response.status_code == 401


def test_refresh_for_inactive_user_returns_401(api_client, teacher):
    refresh = login(api_client, teacher).json()["refresh_token"]
    teacher.status = UserStatus.INACTIVE
    teacher.save(update_fields=["status"])
    response = api_client.post(REFRESH, {"refresh_token": refresh}, format="json")
    assert response.status_code == 401


def test_logout_blacklists_refresh_token(api_client, teacher):
    tokens = login(api_client, teacher).json()
    bearer(api_client, tokens["access_token"])

    response = api_client.post(LOGOUT, {"refresh_token": tokens["refresh_token"]}, format="json")
    assert response.status_code == 204
    assert BlacklistedToken.objects.count() == 1

    again = api_client.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json")
    assert again.status_code == 401


def test_logout_requires_authentication(api_client):
    response = api_client.post(LOGOUT, {"refresh_token": "x"}, format="json")
    assert response.status_code == 401


def test_logout_rejects_other_users_refresh_token(api_client, teacher):
    other = TeacherFactory()
    other_refresh = login(api_client, other).json()["refresh_token"]
    bearer(api_client, login(api_client, teacher).json()["access_token"])

    response = api_client.post(LOGOUT, {"refresh_token": other_refresh}, format="json")
    assert response.status_code == 400
    assert BlacklistedToken.objects.count() == 0


def test_logout_with_invalid_refresh_returns_400(api_client, teacher):
    bearer(api_client, login(api_client, teacher).json()["access_token"])
    response = api_client.post(LOGOUT, {"refresh_token": "garbage"}, format="json")
    assert response.status_code == 400

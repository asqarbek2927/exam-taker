import pytest

pytestmark = pytest.mark.django_db


def test_openapi_schema_is_served_and_valid(api_client):
    response = api_client.get("/api/schema")
    assert response.status_code == 200


def test_malformed_json_returns_400_in_error_format(auth_client, admin):
    client = auth_client(admin)
    response = client.generic(
        "POST", "/api/v1/users", data="{not json", content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Bad Request"


def test_unsupported_media_type(auth_client, admin):
    client = auth_client(admin)
    response = client.generic("POST", "/api/v1/users", data="a=b", content_type="text/plain")
    assert response.status_code == 415
    assert response.json()["status_code"] == 415


def test_method_not_allowed_format(auth_client, admin):
    response = auth_client(admin).put("/api/v1/courses")
    assert response.status_code == 405
    assert response.json()["status_code"] == 405


def test_unknown_api_path_returns_json_404(api_client):
    response = api_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["message"] == "Resurs topilmadi."


def test_non_api_404_stays_html(api_client):
    response = api_client.get("/nope")
    assert response.status_code == 404
    assert "text/html" in response["Content-Type"]

import pytest
from django.utils import timezone

from apps.notifications.choices import NotificationType
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

URL = "/api/v1/notifications"


def create_notification(recipient, **overrides):
    data = {
        "recipient": recipient,
        "type": NotificationType.SYSTEM,
        "title": "Platform update",
        "message": "A new feature is available.",
    }
    data.update(overrides)
    return Notification.objects.create(**data)


def test_list_and_summary_are_scoped_to_current_user(auth_client, student, teacher):
    unread = create_notification(student)
    read = create_notification(student, read_at=timezone.now())
    create_notification(teacher)
    client = auth_client(student)

    listing = client.get(URL)
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()["data"]} == {
        str(unread.id),
        str(read.id),
    }
    assert client.get(f"{URL}/summary").json() == {"total": 2, "unread": 1}
    unread_items = client.get(URL, {"unread_only": "true"}).json()["data"]
    assert [item["id"] for item in unread_items] == [str(unread.id)]


def test_mark_read_is_idempotent_and_cannot_touch_another_inbox(
    auth_client, student, teacher
):
    own = create_notification(student)
    foreign = create_notification(teacher)
    client = auth_client(student)

    for _ in range(2):
        response = client.post(f"{URL}/{own.id}/mark-read")
        assert response.status_code == 200
        assert response.json()["is_read"] is True
        assert response.json()["read_at"] is not None
    assert client.post(f"{URL}/{foreign.id}/mark-read").status_code == 404


def test_mark_all_read_returns_updated_count(auth_client, student):
    create_notification(student)
    create_notification(student)
    create_notification(student, read_at=timezone.now())

    response = auth_client(student).post(f"{URL}/mark-all-read")
    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert not Notification.objects.filter(recipient=student, read_at__isnull=True).exists()


def test_notifications_require_authentication(api_client):
    assert api_client.get(URL).status_code == 401
    assert api_client.get(f"{URL}/summary").status_code == 401

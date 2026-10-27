from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from .models import Notification


def create_notifications(
    *, recipient_ids: Iterable, type: str, title: str, message: str = "", data: dict | None = None
) -> list[Notification]:
    payload = data or {}
    return Notification.objects.bulk_create(
        Notification(
            recipient_id=recipient_id,
            type=type,
            title=title,
            message=message,
            data=payload,
        )
        for recipient_id in set(recipient_ids)
    )


@transaction.atomic
def mark_read(notification: Notification) -> Notification:
    notification = Notification.objects.select_for_update().get(pk=notification.pk)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return notification


def mark_all_read(user) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )

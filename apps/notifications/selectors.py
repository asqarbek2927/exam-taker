from django.db.models import Count, Q

from .models import Notification


def notifications_for(user):
    return Notification.objects.filter(recipient=user)


def notification_summary(user) -> dict[str, int]:
    return notifications_for(user).aggregate(
        total=Count("pk"),
        unread=Count("pk", filter=Q(read_at__isnull=True)),
    )

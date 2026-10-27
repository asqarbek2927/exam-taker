from django.conf import settings
from django.db import models

from common.models import UUIDModel

from .choices import NotificationType


class Notification(UUIDModel):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "read_at", "created_at"],
                name="idx_notification_inbox",
            )
        ]

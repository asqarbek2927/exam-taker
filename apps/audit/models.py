from django.conf import settings
from django.db import models

from common.models import UUIDModel

from .choices import AuditAction


class AuditLog(UUIDModel):
    """Append-only business audit event.

    `metadata` faqat event uchun kerak bo'lgan xavfsiz identifikator va holatlarni
    saqlaydi. Password, token, javob matni va answer key bu jadvalga yozilmaydi.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=40, choices=AuditAction.choices)
    entity_type = models.CharField(max_length=40)
    entity_id = models.UUIDField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["entity_type", "entity_id", "created_at"],
                name="idx_audit_entity_time",
            ),
            models.Index(fields=["actor", "created_at"], name="idx_audit_actor_time"),
            models.Index(fields=["action", "created_at"], name="idx_audit_action_time"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("AuditLog yozuvlari o'zgartirilmaydi.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("AuditLog yozuvlari o'chirilmaydi.")

from django.db import models


class AudienceType(models.TextChoices):
    ALL_COURSE_STUDENTS = "ALL_COURSE_STUDENTS", "All course students"
    GROUPS = "GROUPS", "Groups"
    SPECIFIC_STUDENTS = "SPECIFIC_STUDENTS", "Specific students"


class AssignmentStatus(models.TextChoices):
    """DB da SAQLANADIGAN holat. SCHEDULED/ACTIVE saqlanmaydi (TZ 10.4)."""

    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    PAUSED = "PAUSED", "Paused"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class EffectiveStatus(models.TextChoices):
    """API ga chiqadigan (hisoblanadigan) holat."""

    DRAFT = "DRAFT", "Draft"
    SCHEDULED = "SCHEDULED", "Scheduled"
    ACTIVE = "ACTIVE", "Active"
    PAUSED = "PAUSED", "Paused"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"

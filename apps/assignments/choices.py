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
    ARCHIVED = "ARCHIVED", "Archived"


class AvailabilityType(models.TextChoices):
    TIME_LIMITED = "TIME_LIMITED", "Time limited"
    OPEN_ENDED = "OPEN_ENDED", "Open ended"


class ResultReviewMode(models.TextChoices):
    SCORE_ONLY = "SCORE_ONLY", "Score only"
    AFTER_GRADING = "AFTER_GRADING", "After grading"
    FULL_REVIEW = "FULL_REVIEW", "Full review"


class TransitionAction(models.TextChoices):
    PUBLISH = "PUBLISH", "Publish"
    PAUSE = "PAUSE", "Pause"
    RESUME = "RESUME", "Resume"
    COMPLETE = "COMPLETE", "Complete"
    CANCEL = "CANCEL", "Cancel"
    RESTORE_DRAFT = "RESTORE_DRAFT", "Restore draft"
    ARCHIVE = "ARCHIVE", "Archive"

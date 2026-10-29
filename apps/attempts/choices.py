from django.db import models


class AttemptStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    SUBMITTED = "SUBMITTED", "Submitted"
    PENDING_GRADING = "PENDING_GRADING", "Pending grading"
    GRADED = "GRADED", "Graded"


class FinalizationReason(models.TextChoices):
    USER_SUBMIT = "USER_SUBMIT", "User submit"
    TIMEOUT = "TIMEOUT", "Timeout"
    FOCUS_LIMIT = "FOCUS_LIMIT", "Focus violation limit"
    FULLSCREEN_DECLINED = "FULLSCREEN_DECLINED", "Fullscreen declined"


class AttemptEventType(models.TextChoices):
    TAB_HIDDEN = "TAB_HIDDEN", "Tab hidden"
    TAB_VISIBLE = "TAB_VISIBLE", "Tab visible"
    FULLSCREEN_EXIT = "FULLSCREEN_EXIT", "Fullscreen exit"
    FULLSCREEN_RETURN = "FULLSCREEN_RETURN", "Fullscreen return"
    FULLSCREEN_DECLINED = "FULLSCREEN_DECLINED", "Fullscreen declined"
    COPY = "COPY", "Copy"
    CUT = "CUT", "Cut"
    PASTE = "PASTE", "Paste"


class AttemptEventAction(models.TextChoices):
    WARN = "WARN", "Warn"
    SUBMIT = "SUBMIT", "Submit"

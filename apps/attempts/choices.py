from django.db import models


class AttemptStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    SUBMITTED = "SUBMITTED", "Submitted"
    PENDING_GRADING = "PENDING_GRADING", "Pending grading"
    GRADED = "GRADED", "Graded"

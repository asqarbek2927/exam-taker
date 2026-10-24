from django.db import models


class ExamStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    READY = "READY", "Ready"
    ARCHIVED = "ARCHIVED", "Archived"


class ExamWritableStatus(models.TextChoices):
    """API orqali qo‘lda belgilanadigan holatlar (ARCHIVED — alohida `archive` amali)."""

    DRAFT = "DRAFT", "Draft"
    READY = "READY", "Ready"

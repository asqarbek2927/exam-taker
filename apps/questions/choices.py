from decimal import Decimal

from django.db import models


class QuestionType(models.TextChoices):
    SINGLE_CHOICE = "SINGLE_CHOICE", "Single choice"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE", "Multiple choice"
    TRUE_FALSE = "TRUE_FALSE", "True / False"
    OPEN_ENDED = "OPEN_ENDED", "Open ended"


class QuestionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"
    DELETED = "DELETED", "Deleted"


class QuestionDifficulty(models.TextChoices):
    EASY = "EASY", "Easy"
    MEDIUM = "MEDIUM", "Medium"
    HARD = "HARD", "Hard"


# TZ 8.1: tavsiya etilgan default ballar (faqat `default_points` berilmagan holatda).
DEFAULT_POINTS = {
    QuestionType.SINGLE_CHOICE: Decimal("2"),
    QuestionType.MULTIPLE_CHOICE: Decimal("3"),
    QuestionType.TRUE_FALSE: Decimal("1"),
    QuestionType.OPEN_ENDED: Decimal("5"),
}

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel, VersionedModel

from .choices import QuestionDifficulty, QuestionStatus, QuestionType


class Question(UUIDModel, TimeStampedModel, VersionedModel):
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="questions"
    )
    module = models.ForeignKey(
        "academics.Module", on_delete=models.PROTECT, related_name="questions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="questions"
    )
    type = models.CharField(max_length=20, choices=QuestionType.choices)
    difficulty = models.CharField(
        max_length=10,
        choices=QuestionDifficulty.choices,
        default=QuestionDifficulty.MEDIUM,
        db_index=True,
    )
    text = models.TextField()
    default_points = models.DecimalField(max_digits=6, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=QuestionStatus.choices, default=QuestionStatus.ACTIVE
    )

    class Meta:
        db_table = "questions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["course", "module", "type"], name="idx_question_course_mod_type"),
            models.Index(fields=["course", "status"], name="idx_question_course_status"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(default_points__gte=1),
                name="question_default_points_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(default_points__lte=100),
                name="question_default_points_lte_100",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.type}] {self.text[:50]}"


class QuestionOption(UUIDModel):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "question_options"
        ordering = ["position"]

    def __str__(self) -> str:
        return self.text[:50]

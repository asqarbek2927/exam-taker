from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel, VersionedModel

from .choices import ExamStatus


class Exam(UUIDModel, TimeStampedModel, VersionedModel):
    """Qayta ishlatiladigan imtihon kontenti. Kimga/qachon berilishi `ExamAssignment` da."""

    course = models.ForeignKey("academics.Course", on_delete=models.PROTECT, related_name="exams")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="exams"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    passing_score_percent = models.DecimalField(max_digits=5, decimal_places=2)
    status = models.CharField(max_length=10, choices=ExamStatus.choices, default=ExamStatus.DRAFT)

    class Meta:
        db_table = "exams"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["course", "status"], name="idx_exam_course_status")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(passing_score_percent__gte=0, passing_score_percent__lte=100),
                name="exam_passing_score_0_100",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class ExamModule(UUIDModel):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="exam_modules")
    module = models.ForeignKey(
        "academics.Module", on_delete=models.PROTECT, related_name="exam_modules"
    )

    class Meta:
        db_table = "exam_modules"
        constraints = [
            models.UniqueConstraint(fields=["exam", "module"], name="uniq_exam_module"),
        ]


class ExamQuestion(UUIDModel):
    """Savolning shu imtihondagi ko‘rinishi (`points` — shu exam uchun override)."""

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="exam_questions")
    question = models.ForeignKey(
        "questions.Question", on_delete=models.PROTECT, related_name="exam_questions"
    )
    points = models.DecimalField(max_digits=6, decimal_places=2)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "exam_questions"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["exam", "question"], name="uniq_exam_question"),
            models.CheckConstraint(
                condition=models.Q(points__gte=1), name="exam_question_points_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(points__lte=100), name="exam_question_points_lte_100"
            ),
        ]

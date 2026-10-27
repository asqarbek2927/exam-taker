from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel

from .choices import AttemptStatus, FinalizationReason


class ExamAttempt(UUIDModel, TimeStampedModel):
    assignment = models.ForeignKey(
        "assignments.ExamAssignment", on_delete=models.PROTECT, related_name="attempts"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attempts"
    )
    attempt_number = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    # min(started_at + duration, assignment.end_at) — boshlanganda hisoblanib saqlanadi (TZ 10.5).
    deadline_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    finalization_reason = models.CharField(
        max_length=20, choices=FinalizationReason.choices, null=True, blank=True, db_index=True
    )
    status = models.CharField(
        max_length=20, choices=AttemptStatus.choices, default=AttemptStatus.IN_PROGRESS
    )
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "exam_attempts"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["student", "status"], name="idx_attempt_student_status"),
            models.Index(fields=["assignment", "status"], name="idx_attempt_assignment_status"),
            models.Index(fields=["status", "deadline_at"], name="idx_attempt_status_deadline"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student", "attempt_number"], name="uniq_attempt_number"
            ),
            # Bitta student/assignment — bitta faol attempt (TZ 11.1): parallel startdan himoya.
            models.UniqueConstraint(
                fields=["assignment", "student"],
                condition=models.Q(status="IN_PROGRESS"),
                name="uniq_active_attempt",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student_id} #{self.attempt_number} [{self.status}]"


class StudentAnswer(UUIDModel, TimeStampedModel):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="answers")
    exam_question = models.ForeignKey(
        "exams.ExamQuestion", on_delete=models.PROTECT, related_name="student_answers"
    )
    text_answer = models.TextField(blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    points_awarded = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    teacher_feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="graded_answers",
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "student_answers"
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "exam_question"], name="uniq_answer_per_question"
            ),
        ]


class StudentAnswerOption(UUIDModel):
    student_answer = models.ForeignKey(
        StudentAnswer, on_delete=models.CASCADE, related_name="selected_options"
    )
    option = models.ForeignKey(
        "questions.QuestionOption", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "student_answer_options"
        constraints = [
            models.UniqueConstraint(fields=["student_answer", "option"], name="uniq_answer_option"),
        ]

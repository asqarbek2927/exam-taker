from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel

from .choices import AttemptEventAction, AttemptEventType, AttemptStatus, FinalizationReason


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
    focus_violations = models.PositiveIntegerField(default=0)

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


class AttemptEvent(UUIDModel):
    """Browser integrity signali; client event ID bo'yicha append-only va idempotent."""

    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="events")
    event_id = models.UUIDField()
    type = models.CharField(max_length=30, choices=AttemptEventType.choices)
    client_at = models.DateTimeField()
    details = models.JSONField(default=dict, blank=True)
    counts_violation = models.BooleanField(default=False)
    focus_violations = models.PositiveIntegerField(default=0)
    action = models.CharField(
        max_length=10,
        choices=AttemptEventAction.choices,
        default=AttemptEventAction.WARN,
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attempt_events"
        ordering = ["received_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "event_id"], name="uniq_attempt_client_event"
            )
        ]
        indexes = [models.Index(fields=["attempt", "received_at"], name="idx_attempt_event_time")]


class AttemptQuestion(UUIDModel):
    """Attempt uchun bir marta tanlangan va tartiblangan snapshot savol."""

    attempt = models.ForeignKey(
        ExamAttempt, on_delete=models.CASCADE, related_name="delivery_questions"
    )
    snapshot_question = models.ForeignKey(
        "assignments.AssignmentSnapshotQuestion",
        on_delete=models.PROTECT,
        related_name="attempt_questions",
    )
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "attempt_questions"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "snapshot_question"], name="uniq_attempt_snapshot_question"
            ),
            models.UniqueConstraint(
                fields=["attempt", "position"], name="uniq_attempt_question_position"
            ),
        ]


class AttemptQuestionOption(UUIDModel):
    """Attempt ichida bir marta random qilingan option tartibi."""

    attempt_question = models.ForeignKey(
        AttemptQuestion, on_delete=models.CASCADE, related_name="delivery_options"
    )
    snapshot_option = models.ForeignKey(
        "assignments.AssignmentSnapshotOption",
        on_delete=models.PROTECT,
        related_name="attempt_options",
    )
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "attempt_question_options"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt_question", "snapshot_option"],
                name="uniq_attempt_snapshot_option",
            ),
            models.UniqueConstraint(
                fields=["attempt_question", "position"], name="uniq_attempt_option_position"
            ),
        ]


class StudentAnswer(UUIDModel, TimeStampedModel):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="answers")
    exam_question = models.ForeignKey(
        "exams.ExamQuestion",
        on_delete=models.PROTECT,
        related_name="student_answers",
        null=True,
        blank=True,
    )
    attempt_question = models.ForeignKey(
        AttemptQuestion,
        on_delete=models.PROTECT,
        related_name="answers",
        null=True,
        blank=True,
    )
    revision = models.PositiveIntegerField(default=0)
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
                fields=["attempt", "exam_question"],
                condition=models.Q(exam_question__isnull=False),
                name="uniq_answer_per_question",
            ),
            models.UniqueConstraint(
                fields=["attempt", "attempt_question"],
                condition=models.Q(attempt_question__isnull=False),
                name="uniq_answer_per_attempt_question",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(attempt_question__isnull=False) | models.Q(exam_question__isnull=False)
                ),
                name="answer_has_question_source",
            ),
        ]


class StudentAnswerOption(UUIDModel):
    student_answer = models.ForeignKey(
        StudentAnswer, on_delete=models.CASCADE, related_name="selected_options"
    )
    option = models.ForeignKey(
        "questions.QuestionOption",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    attempt_option = models.ForeignKey(
        AttemptQuestionOption,
        on_delete=models.PROTECT,
        related_name="selected_in_answers",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "student_answer_options"
        constraints = [
            models.UniqueConstraint(
                fields=["student_answer", "option"],
                condition=models.Q(option__isnull=False),
                name="uniq_answer_option",
            ),
            models.UniqueConstraint(
                fields=["student_answer", "attempt_option"],
                condition=models.Q(attempt_option__isnull=False),
                name="uniq_answer_attempt_option",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(option__isnull=False, attempt_option__isnull=True)
                    | models.Q(option__isnull=True, attempt_option__isnull=False)
                ),
                name="answer_option_exactly_one_source",
            ),
        ]

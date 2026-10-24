from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel

from .choices import AssignmentStatus, AudienceType


class ExamAssignment(UUIDModel, TimeStampedModel):
    """Examni ma’lum audience, vaqt, duration va attempt qoidalari bilan e’lon qilish."""

    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT, related_name="assignments")
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="published_assignments"
    )
    audience_type = models.CharField(max_length=20, choices=AudienceType.choices)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)  # NULL = deadline yo‘q
    duration_minutes = models.PositiveIntegerField()
    max_attempts = models.PositiveIntegerField(null=True, blank=True)  # NULL = cheksiz
    status = models.CharField(
        max_length=10, choices=AssignmentStatus.choices, default=AssignmentStatus.DRAFT
    )

    class Meta:
        db_table = "exam_assignments"
        ordering = ["-start_at"]
        indexes = [models.Index(fields=["status", "start_at"], name="idx_assignment_status_start")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True) | models.Q(end_at__gt=models.F("start_at")),
                name="assignment_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0), name="assignment_duration_gt_0"
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__isnull=True) | models.Q(max_attempts__gte=1),
                name="assignment_max_attempts_gte_1",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.exam_id} [{self.audience_type}]"


class ExamAssignmentGroup(UUIDModel):
    assignment = models.ForeignKey(
        ExamAssignment, on_delete=models.CASCADE, related_name="assignment_groups"
    )
    group = models.ForeignKey(
        "academics.StudyGroup", on_delete=models.PROTECT, related_name="assignment_links"
    )

    class Meta:
        db_table = "exam_assignment_groups"
        constraints = [
            models.UniqueConstraint(fields=["assignment", "group"], name="uniq_assignment_group"),
        ]


class ExamAssignmentStudent(UUIDModel):
    assignment = models.ForeignKey(
        ExamAssignment, on_delete=models.CASCADE, related_name="assignment_students"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="specific_assignment_links"
    )

    class Meta:
        db_table = "exam_assignment_students"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"], name="uniq_assignment_student"
            ),
        ]

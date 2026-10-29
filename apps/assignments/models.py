from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel, VersionedModel

from .choices import AssignmentStatus, AudienceType, AvailabilityType, ResultReviewMode


class ExamAssignment(UUIDModel, TimeStampedModel, VersionedModel):
    """Examni ma’lum audience, vaqt, duration va attempt qoidalari bilan e’lon qilish."""

    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT, related_name="assignments")
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="published_assignments"
    )
    audience_type = models.CharField(max_length=20, choices=AudienceType.choices)
    availability_type = models.CharField(
        max_length=20,
        choices=AvailabilityType.choices,
        default=AvailabilityType.TIME_LIMITED,
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)  # NULL = deadline yo‘q
    duration_minutes = models.PositiveIntegerField()
    max_attempts = models.PositiveIntegerField(null=True, blank=True)  # NULL = cheksiz
    result_review_mode = models.CharField(
        max_length=20,
        choices=ResultReviewMode.choices,
        default=ResultReviewMode.SCORE_ONLY,
    )
    answer_review_released = models.BooleanField(default=False)
    answer_review_released_at = models.DateTimeField(null=True, blank=True)
    answer_review_released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="released_assignment_reviews",
        null=True,
        blank=True,
    )
    internal_note = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=AssignmentStatus.choices, default=AssignmentStatus.DRAFT
    )
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

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


class ExamAssignmentRecipient(UUIDModel):
    """Assignment birinchi marta e’lon qilingandagi studentlar snapshoti."""

    assignment = models.ForeignKey(
        ExamAssignment, on_delete=models.CASCADE, related_name="recipients"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignment_recipients"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exam_assignment_recipients"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"], name="uniq_assignment_recipient"
            ),
        ]


class AssignmentSnapshot(UUIDModel):
    """Assignment yaratilgan paytdagi immutable exam metama'lumoti."""

    assignment = models.OneToOneField(
        ExamAssignment, on_delete=models.CASCADE, related_name="snapshot"
    )
    source_exam_id = models.UUIDField()
    source_course_id = models.UUIDField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    passing_score_percent = models.DecimalField(max_digits=5, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assignment_snapshots"


class AssignmentSnapshotQuestion(UUIDModel):
    """Savol va ballning assignmentga muzlatilgan nusxasi."""

    snapshot = models.ForeignKey(
        AssignmentSnapshot, on_delete=models.CASCADE, related_name="questions"
    )
    source_exam_question_id = models.UUIDField()
    source_question_id = models.UUIDField()
    source_module_id = models.UUIDField()
    text = models.TextField()
    type = models.CharField(max_length=20)
    difficulty = models.CharField(max_length=10)
    points = models.DecimalField(max_digits=6, decimal_places=2)
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "assignment_snapshot_questions"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "source_exam_question_id"],
                name="uniq_snapshot_exam_question",
            ),
            models.UniqueConstraint(
                fields=["snapshot", "position"], name="uniq_snapshot_question_position"
            ),
        ]


class AssignmentSnapshotOption(UUIDModel):
    """Option matni va maxfiy answer keyning immutable nusxasi."""

    question = models.ForeignKey(
        AssignmentSnapshotQuestion, on_delete=models.CASCADE, related_name="options"
    )
    source_option_id = models.UUIDField()
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "assignment_snapshot_options"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "source_option_id"], name="uniq_snapshot_source_option"
            ),
            models.UniqueConstraint(
                fields=["question", "position"], name="uniq_snapshot_option_position"
            ),
        ]

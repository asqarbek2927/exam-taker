"""Yozish (write) business logic — assignments."""

from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.academics.choices import CourseStatus, EnrollmentStatus, GroupStatus
from apps.academics.models import Course, Enrollment, StudyGroup
from apps.academics.selectors import has_course_access
from apps.audit.choices import AuditAction
from apps.audit.services import record_audit
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam
from apps.users.models import User
from common.exceptions import AccessDeniedError, BusinessRuleError, ConflictError

from .choices import (
    AssignmentStatus,
    AudienceType,
    AvailabilityType,
    ResultReviewMode,
)
from .models import (
    ExamAssignment,
    ExamAssignmentGroup,
    ExamAssignmentRecipient,
    ExamAssignmentStudent,
)
from .selectors import assignment_has_attempts, effective_status_of
from .snapshots import ensure_assignment_snapshot

# Attempt boshlangan assignmentda faqat staff uchun `internal_note` o'zgaradi.
EDITABLE_AFTER_ATTEMPTS = frozenset({"internal_note"})

TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "publish": (frozenset({AssignmentStatus.DRAFT}), AssignmentStatus.PUBLISHED),
    "pause": (frozenset({AssignmentStatus.PUBLISHED}), AssignmentStatus.PAUSED),
    "resume": (frozenset({AssignmentStatus.PAUSED}), AssignmentStatus.PUBLISHED),
    "complete": (
        frozenset({AssignmentStatus.PUBLISHED, AssignmentStatus.PAUSED}),
        AssignmentStatus.COMPLETED,
    ),
    "cancel": (
        frozenset({AssignmentStatus.DRAFT, AssignmentStatus.PUBLISHED, AssignmentStatus.PAUSED}),
        AssignmentStatus.CANCELLED,
    ),
    "restore": (frozenset({AssignmentStatus.CANCELLED}), AssignmentStatus.DRAFT),
}


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------
def _ensure_course_editable(course: Course) -> None:
    if course.status == CourseStatus.ARCHIVED:
        raise BusinessRuleError("Arxivlangan kursga o‘zgartirish kiritib bo‘lmaydi.")


def _validate_schedule(
    availability_type: str, start_at: datetime | None, end_at: datetime | None
) -> tuple[datetime, datetime | None]:
    if availability_type == AvailabilityType.TIME_LIMITED:
        if start_at is None or end_at is None:
            raise BusinessRuleError("TIME_LIMITED uchun start va end vaqti majburiy.")
    elif availability_type == AvailabilityType.OPEN_ENDED:
        if end_at is not None:
            raise BusinessRuleError("OPEN_ENDED assignmentda end vaqti bo'lmaydi.")
        start_at = start_at or timezone.now()
    else:
        raise BusinessRuleError("Noma'lum availability turi.")
    if end_at is not None and end_at <= start_at:
        raise BusinessRuleError("`end_at` `start_at` dan keyin bo‘lishi kerak.")

    return start_at, end_at


def _validate_not_expired(end_at: datetime | None) -> None:
    if end_at is not None and end_at <= timezone.now():
        raise BusinessRuleError("`end_at` o‘tib ketgan — e’lon qilib bo‘lmaydi.")


def _validate_exam_ready(exam: Exam) -> None:
    if exam.status != ExamStatus.READY:
        raise BusinessRuleError("Faqat READY holatdagi imtihonni e’lon qilish mumkin.")
    if not exam.exam_questions.exists():
        raise BusinessRuleError("Imtihonda kamida 1 ta savol bo‘lishi kerak.")


def _validate_audience(
    course: Course,
    audience_type: str,
    groups: Sequence[StudyGroup],
    students: Sequence[User],
) -> None:
    """TZ 10.2: audience turiga mos ro‘yxat; group/student shu kursga tegishli, ACTIVE yozilgan."""
    if len({g.id for g in groups}) != len(groups):
        raise BusinessRuleError("Guruhlar takrorlanmasligi kerak.")
    if len({s.id for s in students}) != len(students):
        raise BusinessRuleError("Studentlar takrorlanmasligi kerak.")

    if audience_type == AudienceType.ALL_COURSE_STUDENTS:
        if groups or students:
            raise BusinessRuleError(
                "ALL_COURSE_STUDENTS uchun `group_ids` va `student_ids` berilmaydi."
            )
    elif audience_type == AudienceType.GROUPS:
        if not groups:
            raise BusinessRuleError("GROUPS uchun kamida 1 ta guruh tanlang.")
        if students:
            raise BusinessRuleError("GROUPS uchun `student_ids` berilmaydi.")
        for group in groups:
            if group.course_id != course.id:
                raise BusinessRuleError(f"‘{group.name}’ guruhi bu kursga tegishli emas.")
            if group.status != GroupStatus.ACTIVE:
                raise BusinessRuleError(f"‘{group.name}’ guruhi arxivlangan.")
    elif audience_type == AudienceType.SPECIFIC_STUDENTS:
        if not students:
            raise BusinessRuleError("SPECIFIC_STUDENTS uchun kamida 1 ta student tanlang.")
        if groups:
            raise BusinessRuleError("SPECIFIC_STUDENTS uchun `group_ids` berilmaydi.")
        enrolled = set(
            Enrollment.objects.filter(
                course=course,
                status=EnrollmentStatus.ACTIVE,
                student_id__in=[s.id for s in students],
            ).values_list("student_id", flat=True)
        )
        missing = [s.full_name for s in students if s.id not in enrolled]
        if missing:
            raise BusinessRuleError(
                "Quyidagi studentlar kursga (ACTIVE) yozilmagan: " + ", ".join(missing)
            )
    else:
        raise BusinessRuleError("Noma’lum audience turi.")


def _replace_audience(
    assignment: ExamAssignment, groups: Sequence[StudyGroup], students: Sequence[User]
) -> None:
    assignment.assignment_groups.all().delete()
    assignment.assignment_students.all().delete()
    ExamAssignmentGroup.objects.bulk_create(
        ExamAssignmentGroup(assignment=assignment, group=group) for group in groups
    )
    ExamAssignmentStudent.objects.bulk_create(
        ExamAssignmentStudent(assignment=assignment, student=student) for student in students
    )


def _snapshot_recipients(assignment: ExamAssignment) -> None:
    """Birinchi publish paytidagi eligible studentlarni tarix uchun saqlaydi."""
    if assignment.recipients.exists():
        return
    from .selectors import eligible_students

    ExamAssignmentRecipient.objects.bulk_create(
        ExamAssignmentRecipient(assignment=assignment, student_id=student_id)
        for student_id in eligible_students(assignment).values_list("id", flat=True)
    )


def _notify_assignment_published(assignment: ExamAssignment) -> None:
    from apps.notifications.choices import NotificationType
    from apps.notifications.services import create_notifications

    create_notifications(
        recipient_ids=assignment.recipients.values_list("student_id", flat=True),
        type=NotificationType.ASSIGNMENT,
        title="New exam assigned",
        message=f"{assignment.exam.title} is now available.",
        data={
            "assignment_id": str(assignment.id),
            "exam_id": str(assignment.exam_id),
            "course_id": str(assignment.exam.course_id),
        },
    )


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------
@transaction.atomic
def create_assignment(
    *,
    user,
    exam: Exam,
    audience_type: str,
    start_at: datetime,
    end_at: datetime | None,
    duration_minutes: int,
    max_attempts: int | None,
    availability_type: str | None = None,
    result_review_mode: str = ResultReviewMode.SCORE_ONLY,
    internal_note: str = "",
    groups: Sequence[StudyGroup] = (),
    students: Sequence[User] = (),
    is_draft: bool = False,
) -> ExamAssignment:
    course = exam.course
    if not has_course_access(user, course):
        raise AccessDeniedError("Siz bu kursga biriktirilmagansiz.")
    _ensure_course_editable(course)
    _validate_exam_ready(exam)
    availability_type = availability_type or (
        AvailabilityType.OPEN_ENDED if end_at is None else AvailabilityType.TIME_LIMITED
    )
    start_at, end_at = _validate_schedule(availability_type, start_at, end_at)
    if not is_draft:
        _validate_not_expired(end_at)
    _validate_audience(course, audience_type, groups, students)

    assignment = ExamAssignment.objects.create(
        exam=exam,
        published_by=user,
        audience_type=audience_type,
        availability_type=availability_type,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        max_attempts=max_attempts,
        result_review_mode=result_review_mode,
        internal_note=internal_note,
        published_at=None if is_draft else timezone.now(),
        status=AssignmentStatus.DRAFT if is_draft else AssignmentStatus.PUBLISHED,
    )
    ensure_assignment_snapshot(assignment)
    _replace_audience(assignment, groups, students)
    if not is_draft:
        _snapshot_recipients(assignment)
        _notify_assignment_published(assignment)
    return assignment


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------
@transaction.atomic
def update_assignment(*, assignment: ExamAssignment, **fields) -> ExamAssignment:
    """`fields`: audience_type, groups, students, start_at, end_at, duration_minutes,
    max_attempts."""
    assignment = (
        ExamAssignment.objects.select_for_update(of=("self",))
        .select_related("exam__course")
        .get(pk=assignment.pk)
    )
    expected_version = fields.pop("expected_version", None)
    if expected_version is not None and expected_version != assignment.version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {assignment.version}.")
    _ensure_not_archived(assignment)
    if effective_status_of(assignment) in (
        AssignmentStatus.COMPLETED,
        AssignmentStatus.CANCELLED,
    ):
        raise BusinessRuleError(
            "Yakunlangan yoki bekor qilingan e’lonni tahrirlab bo‘lmaydi "
            "(bekor qilingan bo‘lsa — avval `restore`)."
        )
    _ensure_course_editable(assignment.exam.course)
    if not fields:
        return assignment

    if assignment_has_attempts(assignment):
        _check_editable_after_attempts(assignment, fields)

    availability_type = fields.get("availability_type", assignment.availability_type)
    if "availability_type" not in fields and "end_at" in fields:
        availability_type = (
            AvailabilityType.OPEN_ENDED
            if fields["end_at"] is None
            else AvailabilityType.TIME_LIMITED
        )
        fields["availability_type"] = availability_type
    start_at = fields.get("start_at", assignment.start_at)
    end_at = fields.get("end_at", assignment.end_at)
    start_at, end_at = _validate_schedule(availability_type, start_at, end_at)
    if "end_at" in fields and assignment.status != AssignmentStatus.DRAFT:
        _validate_not_expired(end_at)

    audience_changed = {"audience_type", "groups", "students"} & fields.keys()
    if audience_changed:
        current_type = assignment.audience_type
        audience_type = fields.get("audience_type", current_type)
        same_type = audience_type == current_type
        groups = fields.get(
            "groups",
            [link.group for link in assignment.assignment_groups.select_related("group")]
            if same_type
            else [],
        )
        students = fields.get(
            "students",
            [link.student for link in assignment.assignment_students.select_related("student")]
            if same_type
            else [],
        )
        _validate_audience(assignment.exam.course, audience_type, groups, students)
        assignment.audience_type = audience_type
        _replace_audience(assignment, groups, students)

    fields["start_at"] = start_at
    fields["end_at"] = end_at
    for name in (
        "availability_type",
        "start_at",
        "end_at",
        "duration_minutes",
        "max_attempts",
        "result_review_mode",
        "internal_note",
    ):
        if name in fields:
            setattr(assignment, name, fields[name])
    assignment.version += 1
    assignment.save()
    return assignment


def _check_editable_after_attempts(assignment: ExamAssignment, fields: dict) -> None:
    locked_fields = set(fields) - EDITABLE_AFTER_ATTEMPTS
    if locked_fields:
        raise ConflictError(
            "Attempt boshlangan assignmentda faqat internal_note o'zgarishi mumkin "
            f"(locked: {', '.join(sorted(locked_fields))})."
        )


# --------------------------------------------------------------------------
# Status transitions
# --------------------------------------------------------------------------
@transaction.atomic
def transition(
    *,
    assignment: ExamAssignment,
    action: str,
    expected_version: int | None = None,
    actor=None,
) -> ExamAssignment:
    action = action.lower()
    if action == "archive":
        return archive_assignment(
            assignment=assignment,
            expected_version=expected_version,
            actor=actor,
        )
    sources, target = TRANSITIONS[action]
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if expected_version is not None and expected_version != assignment.version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {assignment.version}.")
    _ensure_not_archived(assignment)
    if assignment.status not in sources:
        raise ConflictError(f"`{action}` amalini {assignment.status} holatida bajarib bo‘lmaydi.")
    effective_status = effective_status_of(assignment)
    if action == "pause" and effective_status != "ACTIVE":
        raise ConflictError("`pause` faqat ACTIVE assignment uchun mumkin.")
    if (
        action == "complete"
        and assignment.status == AssignmentStatus.PUBLISHED
        and effective_status != "ACTIVE"
    ):
        raise ConflictError("`complete` faqat ACTIVE yoki PAUSED assignment uchun mumkin.")
    if action == "resume" and (
        assignment.start_at > timezone.now()
        or (assignment.end_at is not None and assignment.end_at <= timezone.now())
    ):
        raise ConflictError("`resume` faqat availability oynasi ichida mumkin.")
    first_publish = action == "publish" and assignment.published_at is None
    if action == "publish":
        _ensure_course_editable(assignment.exam.course)
        _validate_exam_ready(assignment.exam)
        _validate_schedule(assignment.availability_type, assignment.start_at, assignment.end_at)
        _validate_not_expired(assignment.end_at)
        _snapshot_recipients(assignment)
        if assignment.published_at is None:
            assignment.published_at = timezone.now()
    source_status = assignment.status
    assignment.status = target
    assignment.version += 1
    update_fields = ["status", "version", "updated_at"]
    if action == "publish":
        update_fields.append("published_at")
    assignment.save(update_fields=update_fields)
    if first_publish:
        _notify_assignment_published(assignment)
    record_audit(
        actor=actor,
        action=AuditAction.ASSIGNMENT_TRANSITION,
        entity_type="assignment",
        entity_id=assignment.pk,
        metadata={
            "transition": action.upper(),
            "from_status": source_status,
            "to_status": target,
            "version": assignment.version,
        },
    )
    return assignment


def _ensure_not_archived(assignment: ExamAssignment) -> None:
    if assignment.is_archived:
        raise BusinessRuleError("Arxivlangan assignmentni avval arxivdan qaytaring.")


@transaction.atomic
def archive_assignment(
    *, assignment: ExamAssignment, expected_version: int | None = None, actor=None
) -> ExamAssignment:
    """Faqat yakunlangan/bekor qilingan assignmentni katalogdan arxivlaydi."""
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if expected_version is not None and expected_version != assignment.version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {assignment.version}.")
    if assignment.is_archived:
        return assignment

    from .selectors import effective_status_of

    if effective_status_of(assignment) not in {
        AssignmentStatus.COMPLETED,
        AssignmentStatus.CANCELLED,
    }:
        raise BusinessRuleError("Faqat COMPLETED yoki CANCELLED assignmentni arxivlash mumkin.")
    assignment.is_archived = True
    assignment.archived_at = timezone.now()
    assignment.version += 1
    assignment.save(update_fields=["is_archived", "archived_at", "version", "updated_at"])
    record_audit(
        actor=actor,
        action=AuditAction.ASSIGNMENT_TRANSITION,
        entity_type="assignment",
        entity_id=assignment.pk,
        metadata={
            "transition": "ARCHIVE",
            "from_status": assignment.status,
            "to_status": "ARCHIVED",
            "version": assignment.version,
        },
    )
    return assignment


@transaction.atomic
def unarchive_assignment(*, assignment: ExamAssignment, actor=None) -> ExamAssignment:
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if not assignment.is_archived:
        return assignment
    assignment.is_archived = False
    assignment.archived_at = None
    assignment.version += 1
    assignment.save(update_fields=["is_archived", "archived_at", "version", "updated_at"])
    record_audit(
        actor=actor,
        action=AuditAction.ASSIGNMENT_TRANSITION,
        entity_type="assignment",
        entity_id=assignment.pk,
        metadata={
            "transition": "UNARCHIVE",
            "from_status": "ARCHIVED",
            "to_status": assignment.status,
            "version": assignment.version,
        },
    )
    return assignment


@transaction.atomic
def delete_unused_assignment(*, assignment: ExamAssignment, actor=None) -> None:
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if assignment.attempts.exists():
        raise ConflictError("ASSIGNMENT_USED: attempt boshlangan assignment o'chirilmaydi.")
    record_audit(
        actor=actor,
        action=AuditAction.ASSIGNMENT_DELETED,
        entity_type="assignment",
        entity_id=assignment.pk,
        metadata={
            "status": assignment.status,
            "exam_id": assignment.exam_id,
            "version": assignment.version,
        },
    )
    assignment.delete()


def review_policy(assignment: ExamAssignment) -> dict:
    from apps.attempts.choices import AttemptStatus

    attempts = assignment.attempts.all()
    in_progress = attempts.filter(status=AttemptStatus.IN_PROGRESS).count()
    submitted = attempts.exclude(status=AttemptStatus.IN_PROGRESS).count()
    graded = attempts.filter(status=AttemptStatus.GRADED).count()
    closed = (
        effective_status_of(assignment)
        in {
            AssignmentStatus.COMPLETED,
            AssignmentStatus.CANCELLED,
        }
        or assignment.is_archived
    )
    blocked_reasons = []
    if not closed:
        blocked_reasons.append("ASSIGNMENT_NOT_CLOSED")
    if submitted == 0:
        blocked_reasons.append("NO_SUBMITTED_ATTEMPTS")
    if in_progress:
        blocked_reasons.append("ATTEMPTS_IN_PROGRESS")
    if submitted != graded:
        blocked_reasons.append("GRADING_INCOMPLETE")
    return {
        "mode": assignment.result_review_mode,
        "released": assignment.answer_review_released,
        "can_release": not blocked_reasons and not assignment.answer_review_released,
        "blocked_reasons": blocked_reasons,
        "submitted_count": submitted,
        "graded_count": graded,
        "in_progress_count": in_progress,
    }


@transaction.atomic
def release_answer_review(
    *, assignment: ExamAssignment, released_by, expected_version: int | None = None
) -> ExamAssignment:
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if assignment.answer_review_released:
        return assignment
    if expected_version is not None and expected_version != assignment.version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {assignment.version}.")
    # Submit/grading bilan parallel release bo'lmasligi uchun mavjud attemptlar
    # shu transaction tugaguncha bloklanadi.
    list(assignment.attempts.select_for_update(of=("self",)).values_list("pk", flat=True))
    policy = review_policy(assignment)
    if not policy["can_release"]:
        raise ConflictError("REVIEW_NOT_RELEASABLE: " + ", ".join(policy["blocked_reasons"]))
    assignment.result_review_mode = ResultReviewMode.FULL_REVIEW
    assignment.answer_review_released = True
    assignment.answer_review_released_at = timezone.now()
    assignment.answer_review_released_by = released_by
    assignment.version += 1
    assignment.save(
        update_fields=[
            "result_review_mode",
            "answer_review_released",
            "answer_review_released_at",
            "answer_review_released_by",
            "version",
            "updated_at",
        ]
    )
    record_audit(
        actor=released_by,
        action=AuditAction.ANSWER_REVIEW_RELEASED,
        entity_type="assignment",
        entity_id=assignment.pk,
        metadata={
            "result_review_mode": assignment.result_review_mode,
            "version": assignment.version,
            "submitted_count": policy["submitted_count"],
            "graded_count": policy["graded_count"],
        },
    )
    return assignment

"""Yozish (write) business logic — assignments."""

from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.academics.choices import CourseStatus, EnrollmentStatus, GroupStatus
from apps.academics.models import Course, Enrollment, StudyGroup
from apps.academics.selectors import has_course_access
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam
from apps.users.models import User
from common.exceptions import AccessDeniedError, BusinessRuleError, ConflictError

from .choices import AssignmentStatus, AudienceType
from .models import (
    ExamAssignment,
    ExamAssignmentGroup,
    ExamAssignmentRecipient,
    ExamAssignmentStudent,
)
from .selectors import assignment_has_attempts

# Attempt boshlangan assignmentda faqat `end_at` uzaytirish mumkin (TZ 10.4).
EDITABLE_AFTER_ATTEMPTS = frozenset({"end_at"})

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


def _validate_schedule(start_at: datetime, end_at: datetime | None) -> None:
    if end_at is not None and end_at <= start_at:
        raise BusinessRuleError("`end_at` `start_at` dan keyin bo‘lishi kerak.")


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
        groups: Sequence[StudyGroup] = (),
        students: Sequence[User] = (),
        is_draft: bool = False,
) -> ExamAssignment:
    course = exam.course
    if not has_course_access(user, course):
        raise AccessDeniedError("Siz bu kursga biriktirilmagansiz.")
    _ensure_course_editable(course)
    _validate_exam_ready(exam)
    _validate_schedule(start_at, end_at)
    if not is_draft:
        _validate_not_expired(end_at)
    _validate_audience(course, audience_type, groups, students)

    assignment = ExamAssignment.objects.create(
        exam=exam,
        published_by=user,
        audience_type=audience_type,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        max_attempts=max_attempts,
        published_at=None if is_draft else timezone.now(),
        status=AssignmentStatus.DRAFT if is_draft else AssignmentStatus.PUBLISHED,
    )
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
    _ensure_not_archived(assignment)
    if assignment.status in (AssignmentStatus.COMPLETED, AssignmentStatus.CANCELLED):
        raise BusinessRuleError(
            "Yakunlangan yoki bekor qilingan e’lonni tahrirlab bo‘lmaydi "
            "(bekor qilingan bo‘lsa — avval `restore`)."
        )
    _ensure_course_editable(assignment.exam.course)
    if not fields:
        return assignment

    if assignment_has_attempts(assignment):
        _check_editable_after_attempts(assignment, fields)

    start_at = fields.get("start_at", assignment.start_at)
    end_at = fields.get("end_at", assignment.end_at)
    _validate_schedule(start_at, end_at)
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

    for name in ("start_at", "end_at", "duration_minutes", "max_attempts"):
        if name in fields:
            setattr(assignment, name, fields[name])
    assignment.save()
    return assignment


def _check_editable_after_attempts(assignment: ExamAssignment, fields: dict) -> None:
    locked = set(fields) - EDITABLE_AFTER_ATTEMPTS
    if locked:
        raise ConflictError(
            "Attempt boshlangan e’londa faqat `end_at` ni uzaytirish mumkin "
            f"(o‘zgartirib bo‘lmaydi: {', '.join(sorted(locked))})."
        )
    new_end = fields["end_at"]
    if new_end is None:
        return  # deadline ni olib tashlash = uzaytirish
    if assignment.end_at is None or new_end <= assignment.end_at:
        raise ConflictError("Attempt boshlangan e’londa `end_at` faqat uzaytirilishi mumkin.")


# --------------------------------------------------------------------------
# Status transitions
# --------------------------------------------------------------------------
@transaction.atomic
def transition(*, assignment: ExamAssignment, action: str) -> ExamAssignment:
    sources, target = TRANSITIONS[action]
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    _ensure_not_archived(assignment)
    if assignment.status not in sources:
        raise ConflictError(f"`{action}` amalini {assignment.status} holatida bajarib bo‘lmaydi.")
    first_publish = action == "publish" and assignment.published_at is None
    if action == "publish":
        _ensure_course_editable(assignment.exam.course)
        _validate_exam_ready(assignment.exam)
        _validate_not_expired(assignment.end_at)
        _snapshot_recipients(assignment)
        if assignment.published_at is None:
            assignment.published_at = timezone.now()
    assignment.status = target
    update_fields = ["status", "updated_at"]
    if action == "publish":
        update_fields.append("published_at")
    assignment.save(update_fields=update_fields)
    if first_publish:
        _notify_assignment_published(assignment)
    return assignment


def _ensure_not_archived(assignment: ExamAssignment) -> None:
    if assignment.is_archived:
        raise BusinessRuleError("Arxivlangan assignmentni avval arxivdan qaytaring.")


@transaction.atomic
def archive_assignment(*, assignment: ExamAssignment) -> ExamAssignment:
    """Faqat yakunlangan/bekor qilingan assignmentni katalogdan arxivlaydi."""
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if assignment.is_archived:
        return assignment

    from .selectors import effective_status_of

    if effective_status_of(assignment) not in {
        AssignmentStatus.COMPLETED,
        AssignmentStatus.CANCELLED,
    }:
        raise BusinessRuleError(
            "Faqat COMPLETED yoki CANCELLED assignmentni arxivlash mumkin."
        )
    assignment.is_archived = True
    assignment.archived_at = timezone.now()
    assignment.save(update_fields=["is_archived", "archived_at", "updated_at"])
    return assignment


@transaction.atomic
def unarchive_assignment(*, assignment: ExamAssignment) -> ExamAssignment:
    assignment = ExamAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if not assignment.is_archived:
        return assignment
    assignment.is_archived = False
    assignment.archived_at = None
    assignment.save(update_fields=["is_archived", "archived_at", "updated_at"])
    return assignment

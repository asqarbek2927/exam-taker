"""O‘qish querylari — assignments (status hisoblash, audience/eligibility)."""

from datetime import datetime
from decimal import Decimal

from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.academics.choices import EnrollmentStatus
from apps.academics.models import CourseTeacher, Enrollment, GroupStudent
from apps.users.choices import UserRole, UserStatus
from apps.users.models import User

from .choices import AssignmentStatus, AudienceType, EffectiveStatus
from .models import (
    AssignmentSnapshotQuestion,
    ExamAssignment,
    ExamAssignmentGroup,
    ExamAssignmentStudent,
)


# --------------------------------------------------------------------------
# Hisoblanadigan status (TZ 10.4)
# --------------------------------------------------------------------------
def effective_status_of(assignment: ExamAssignment, now: datetime | None = None) -> str:
    """Python tomonidagi hisob. `effective_status_expr` bilan bir xil (testlar tekshiradi)."""
    now = now or timezone.now()
    if assignment.is_archived:
        return EffectiveStatus.ARCHIVED
    if assignment.status != AssignmentStatus.PUBLISHED:
        return str(assignment.status)
    if assignment.start_at > now:
        return EffectiveStatus.SCHEDULED
    if assignment.end_at is not None and assignment.end_at <= now:
        return EffectiveStatus.COMPLETED
    return EffectiveStatus.ACTIVE


def effective_status_expr(now: datetime) -> Case:
    """ORM tomonidagi hisob — filterlash va annotatsiya uchun."""
    published = AssignmentStatus.PUBLISHED
    return Case(
        When(is_archived=True, then=Value(EffectiveStatus.ARCHIVED)),
        When(status=published, start_at__gt=now, then=Value(EffectiveStatus.SCHEDULED)),
        When(status=published, end_at__lte=now, then=Value(EffectiveStatus.COMPLETED)),
        When(status=published, then=Value(EffectiveStatus.ACTIVE)),
        default=F("status"),  # DRAFT / PAUSED / COMPLETED / CANCELLED — nomlari bir xil
        output_field=CharField(),
    )


def with_effective_status(qs: QuerySet[ExamAssignment], now: datetime | None = None):
    return qs.annotate(effective_status=effective_status_expr(now or timezone.now()))


# --------------------------------------------------------------------------
# Staff (Super Admin / Teacher)
# --------------------------------------------------------------------------
def staff_visible(user) -> QuerySet[ExamAssignment]:
    qs = ExamAssignment.objects.all()
    if user.role == UserRole.SUPER_ADMIN:
        return qs
    if user.role == UserRole.TEACHER:
        return qs.filter(
            exam__course_id__in=CourseTeacher.objects.filter(teacher=user).values("course_id")
        )
    return qs.none()


def staff_assignments(qs: QuerySet[ExamAssignment], now: datetime | None = None):
    return (
        with_effective_status(qs, now)
        .select_related("exam__course", "published_by")
        .annotate(attempts_count=Count("attempts", distinct=True))
        .prefetch_related(
            Prefetch(
                "assignment_groups",
                queryset=ExamAssignmentGroup.objects.select_related("group").order_by(
                    "group__name"
                ),
            ),
            Prefetch(
                "assignment_students",
                queryset=ExamAssignmentStudent.objects.select_related("student").order_by(
                    "student__full_name"
                ),
            ),
        )
    )


def assignment_directory_summary(user, now: datetime | None = None) -> dict[str, int]:
    """Staff assignment katalogining joriy (arxivlanmagan) kartochka hisoblari."""
    qs = with_effective_status(staff_visible(user).filter(is_archived=False), now)
    return qs.aggregate(
        assignments=Count("pk"),
        active=Count("pk", filter=Q(effective_status=EffectiveStatus.ACTIVE)),
        scheduled=Count("pk", filter=Q(effective_status=EffectiveStatus.SCHEDULED)),
        paused=Count("pk", filter=Q(effective_status=EffectiveStatus.PAUSED)),
    )


# --------------------------------------------------------------------------
# Eligibility (TZ 10.2) — yagona joy
# --------------------------------------------------------------------------
def eligible_students(assignment: ExamAssignment) -> QuerySet[User]:
    """Audience ∩ kursga ACTIVE yozilgan ∩ ACTIVE foydalanuvchi."""
    enrolled = Enrollment.objects.filter(
        course_id=assignment.exam.course_id, status=EnrollmentStatus.ACTIVE
    ).values("student_id")
    students = User.objects.filter(role=UserRole.STUDENT, status=UserStatus.ACTIVE, id__in=enrolled)

    if assignment.audience_type == AudienceType.GROUPS:
        in_groups = GroupStudent.objects.filter(
            group_id__in=assignment.assignment_groups.values("group_id")
        ).values("student_id")
        return students.filter(id__in=in_groups)
    if assignment.audience_type == AudienceType.SPECIFIC_STUDENTS:
        return students.filter(id__in=assignment.assignment_students.values("student_id"))
    return students


def is_student_eligible(assignment: ExamAssignment, student: User) -> bool:
    return eligible_students(assignment).filter(pk=student.pk).exists()


def student_assignments(student: User, now: datetime | None = None):
    """Student ko‘radigan assignmentlar (DRAFT/CANCELLED yashirin) + o‘z attempt statistikasi."""
    from apps.attempts.choices import AttemptStatus  # lazy: aylanma import bo‘lmasligi uchun
    from apps.attempts.models import ExamAttempt

    enrolled = Enrollment.objects.filter(
        student=student,
        status=EnrollmentStatus.ACTIVE,
        course_id=OuterRef("exam__course_id"),
    )
    in_group = ExamAssignmentGroup.objects.filter(
        assignment=OuterRef("pk"), group__group_students__student=student
    )
    specific = ExamAssignmentStudent.objects.filter(assignment=OuterRef("pk"), student=student)

    audience = (
        Q(audience_type=AudienceType.ALL_COURSE_STUDENTS)
        | (Q(audience_type=AudienceType.GROUPS) & Q(Exists(in_group)))
        | (Q(audience_type=AudienceType.SPECIFIC_STUDENTS) & Q(Exists(specific)))
    )
    own_attempts = ExamAttempt.objects.filter(assignment=OuterRef("pk"), student=student)

    qs = (
        ExamAssignment.objects.filter(
            is_archived=False,
            status__in=[
                AssignmentStatus.PUBLISHED,
                AssignmentStatus.PAUSED,
                AssignmentStatus.COMPLETED,
            ],
        )
        .filter(Exists(enrolled))
        .filter(audience)
    )
    return (
        with_effective_status(qs, now)
        .select_related("exam__course")
        .annotate(
            attempts_used=Coalesce(
                Subquery(
                    own_attempts.order_by()
                    .values("assignment")
                    .annotate(n=Count("pk"))
                    .values("n"),
                    output_field=IntegerField(),
                ),
                0,
            ),
            active_attempt_id=Subquery(
                own_attempts.filter(status=AttemptStatus.IN_PROGRESS).values("id")[:1]
            ),
            questions_count=Coalesce(
                Subquery(
                    AssignmentSnapshotQuestion.objects.filter(
                        snapshot__assignment_id=OuterRef("pk")
                    )
                    .order_by()
                    .values("snapshot__assignment_id")
                    .annotate(n=Count("pk"))
                    .values("n"),
                    output_field=IntegerField(),
                ),
                0,
            ),
            total_points=Coalesce(
                Subquery(
                    AssignmentSnapshotQuestion.objects.filter(
                        snapshot__assignment_id=OuterRef("pk")
                    )
                    .order_by()
                    .values("snapshot__assignment_id")
                    .annotate(total=Sum("points"))
                    .values("total"),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                ),
                Decimal("0"),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            ),
        )
    )


def assignment_has_attempts(assignment: ExamAssignment) -> bool:
    return assignment.attempts.exists()


__all__ = [
    "assignment_directory_summary",
    "assignment_has_attempts",
    "effective_status_expr",
    "effective_status_of",
    "eligible_students",
    "is_student_eligible",
    "staff_assignments",
    "staff_visible",
    "student_assignments",
    "with_effective_status",
]

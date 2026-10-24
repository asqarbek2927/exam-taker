"""Results va Dashboard hisob-kitoblari. Statistika DB da saqlanmaydi — manba jadvallardan
hisoblanadi (TZ 12.2). Modelsiz app."""

from datetime import datetime

from django.db.models import (
    Avg,
    BooleanField,
    Count,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.utils import timezone

from apps.academics.choices import CourseStatus, EnrollmentStatus, ModuleStatus
from apps.academics.models import Course, CourseTeacher, Enrollment, Module, StudyGroup
from apps.assignments.choices import EffectiveStatus
from apps.assignments.models import ExamAssignment
from apps.assignments.selectors import student_assignments, with_effective_status
from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt
from apps.attempts.selectors import attempts_visible_to
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam
from apps.questions.choices import QuestionStatus
from apps.questions.models import Question
from apps.users.choices import UserRole, UserStatus
from apps.users.models import User

RESULT_STATUSES = (AttemptStatus.SUBMITTED, AttemptStatus.PENDING_GRADING, AttemptStatus.GRADED)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
def results_visible_to(user) -> QuerySet[ExamAttempt]:
    """Yakunlangan attemptlar: Student — o‘ziniki, Teacher — o‘z kurslari, Admin — hammasi."""
    return attempts_visible_to(user).filter(status__in=RESULT_STATUSES)


def _latest_pk(statuses):
    """Har (assignment, student) uchun oxirgi (eng katta `attempt_number`) attempt PK si."""
    return Subquery(
        ExamAttempt.objects.filter(
            assignment=OuterRef("assignment"), student=OuterRef("student"), status__in=statuses
        )
        .order_by("-attempt_number")
        .values("pk")[:1]
    )


def only_latest(qs: QuerySet[ExamAttempt], statuses=RESULT_STATUSES) -> QuerySet[ExamAttempt]:
    return qs.filter(pk=_latest_pk(statuses))


def with_is_latest(qs: QuerySet[ExamAttempt]) -> QuerySet[ExamAttempt]:
    """`is_latest` — joriy (current) natija shu attemptmi (TZ 12.1: latest attempt asosida)."""
    return qs.annotate(
        is_latest=ExpressionWrapper(Q(pk=_latest_pk(RESULT_STATUSES)), output_field=BooleanField())
    )


# --------------------------------------------------------------------------
# Umumiy hisob-kitoblar
# --------------------------------------------------------------------------
def score_stats(attempts: QuerySet[ExamAttempt]) -> tuple[float | None, float | None]:
    """`(o‘rtacha foiz, o‘tish foizi)` — har (assignment, student) uchun OXIRGI baholangan attempt
    bo‘yicha. Ma’lumot yo‘q bo‘lsa — `(None, None)`."""
    latest_graded = only_latest(
        attempts.filter(status=AttemptStatus.GRADED), [AttemptStatus.GRADED]
    )
    stats = latest_graded.aggregate(
        average=Avg("percentage"),
        total=Count("pk"),
        passed=Count("pk", filter=Q(passed=True)),
    )
    if not stats["total"]:
        return None, None
    average = round(float(stats["average"]), 2)
    pass_rate = round(stats["passed"] * 100 / stats["total"], 2)
    return average, pass_rate


def _count_effective(qs: QuerySet[ExamAssignment], status: str, now: datetime) -> int:
    return with_effective_status(qs, now).filter(effective_status=status).count()


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def admin_dashboard(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    average, pass_rate = score_stats(ExamAttempt.objects.all())
    active_users = User.objects.filter(status=UserStatus.ACTIVE)
    assignments = ExamAssignment.objects.all()
    return {
        "total_students": active_users.filter(role=UserRole.STUDENT).count(),
        "total_teachers": active_users.filter(role=UserRole.TEACHER).count(),
        "total_courses": Course.objects.filter(status=CourseStatus.ACTIVE).count(),
        "total_modules": Module.objects.filter(status=ModuleStatus.ACTIVE).count(),
        "total_questions": Question.objects.filter(status=QuestionStatus.ACTIVE).count(),
        "total_exams": Exam.objects.exclude(status=ExamStatus.ARCHIVED).count(),
        "active_assignments": _count_effective(assignments, EffectiveStatus.ACTIVE, now),
        "completed_assignments": _count_effective(assignments, EffectiveStatus.COMPLETED, now),
        "average_score": average,
        "pass_rate": pass_rate,
    }


def teacher_dashboard(teacher, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    course_ids = list(
        CourseTeacher.objects.filter(
            teacher=teacher, course__status=CourseStatus.ACTIVE
        ).values_list("course_id", flat=True)
    )
    attempts = attempts_visible_to(teacher)
    average, _ = score_stats(attempts)
    return {
        "my_courses": len(course_ids),
        "my_groups": StudyGroup.objects.filter(course_id__in=course_ids).count(),
        "my_students": Enrollment.objects.filter(
            course_id__in=course_ids, status=EnrollmentStatus.ACTIVE
        )
        .values("student_id")
        .distinct()
        .count(),
        "my_questions": Question.objects.filter(
            created_by=teacher, status=QuestionStatus.ACTIVE
        ).count(),
        "my_exams": Exam.objects.filter(created_by=teacher)
        .exclude(status=ExamStatus.ARCHIVED)
        .count(),
        "active_assignments": _count_effective(
            ExamAssignment.objects.filter(published_by=teacher), EffectiveStatus.ACTIVE, now
        ),
        "pending_grading": attempts.filter(status=AttemptStatus.PENDING_GRADING).count(),
        "average_student_score": average,
    }


def student_dashboard(student, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    own_attempts = ExamAttempt.objects.filter(student=student)
    average, _ = score_stats(own_attempts)

    latest_graded = only_latest(
        own_attempts.filter(status=AttemptStatus.GRADED), [AttemptStatus.GRADED]
    )
    available = (
        student_assignments(student, now)
        .filter(effective_status=EffectiveStatus.ACTIVE)
        .filter(
            Q(active_attempt_id__isnull=False)
            | Q(max_attempts__isnull=True)
            | Q(attempts_used__lt=F("max_attempts"))
        )
        .count()
    )
    return {
        "my_courses": Enrollment.objects.filter(
            student=student, status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED]
        ).count(),
        "available_exams": available,
        "completed_exams": own_attempts.filter(status__in=RESULT_STATUSES)
        .values("assignment_id")
        .distinct()
        .count(),
        "average_score": average,
        "passed_exams": latest_graded.filter(passed=True).count(),
    }

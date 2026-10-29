"""O'qish querylari — users."""

from django.db.models import (
    Avg,
    Count,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce

from apps.academics.choices import CourseStatus, EnrollmentStatus
from apps.academics.models import CourseTeacher, Enrollment
from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam

from .choices import UserRole, UserStatus
from .models import User


def _count_for_user(model, user_field: str, **filters):
    subquery = (
        model.objects.filter(**{user_field: OuterRef("pk")}, **filters)
        .order_by()
        .values(user_field)
        .annotate(n=Count("pk", distinct=True))
        .values("n")
    )
    return Coalesce(Subquery(subquery, output_field=IntegerField()), 0)


def teacher_directory() -> QuerySet[User]:
    """Teacher kartalari uchun kurs va hisoblangan statistikalarni tayyorlaydi."""
    active_course_assignments = CourseTeacher.objects.filter(
        course__status=CourseStatus.ACTIVE
    ).select_related("course")

    return (
        User.objects.filter(role=UserRole.TEACHER)
        .annotate(
            courses_count=_count_for_user(
                CourseTeacher,
                "teacher",
                course__status=CourseStatus.ACTIVE,
            ),
            students_count=_count_for_user(
                Enrollment,
                "course__course_teachers__teacher",
                course__status=CourseStatus.ACTIVE,
                status=EnrollmentStatus.ACTIVE,
                student__status=UserStatus.ACTIVE,
            ),
            exams_count=_count_for_user(
                Exam,
                "course__course_teachers__teacher",
                course__status=CourseStatus.ACTIVE,
                status__in=[ExamStatus.DRAFT, ExamStatus.READY],
            ),
        )
        .prefetch_related(
            Prefetch(
                "course_assignments",
                queryset=active_course_assignments,
                to_attr="active_course_assignments",
            )
        )
    )


def teacher_directory_summary() -> dict:
    """Teacher directory tepasidagi umumiy ko'rsatkichlar."""
    teacher_counts = User.objects.filter(role=UserRole.TEACHER).aggregate(
        active_teachers=Count("pk", filter=Q(status=UserStatus.ACTIVE)),
        inactive_teachers=Count("pk", filter=Q(status=UserStatus.INACTIVE)),
        total_teachers=Count("pk"),
    )
    course_assignments = CourseTeacher.objects.filter(
        course__status=CourseStatus.ACTIVE,
        teacher__role=UserRole.TEACHER,
    ).count()
    # Join ataylab teacher kesimida sanaydi: bitta enrollment kursdagi har bir
    # teacher kartasining students_count qiymatiga bittadan qo'shiladi.
    students_taught = Enrollment.objects.filter(
        course__status=CourseStatus.ACTIVE,
        status=EnrollmentStatus.ACTIVE,
        student__status=UserStatus.ACTIVE,
        course__course_teachers__teacher__role=UserRole.TEACHER,
    ).count()

    return {
        **teacher_counts,
        "students_taught": students_taught,
        "course_assignments": course_assignments,
    }


RESULT_STATUSES = (
    AttemptStatus.SUBMITTED,
    AttemptStatus.PENDING_GRADING,
    AttemptStatus.GRADED,
)


def _latest_graded_pk():
    return Subquery(
        ExamAttempt.objects.filter(
            assignment_id=OuterRef("assignment_id"),
            student_id=OuterRef("student_id"),
            status=AttemptStatus.GRADED,
        )
        .order_by("-attempt_number")
        .values("pk")[:1]
    )


def _latest_graded_attempts_for_outer_student() -> QuerySet[ExamAttempt]:
    return (
        ExamAttempt.objects.filter(student_id=OuterRef("pk"), status=AttemptStatus.GRADED)
        .annotate(latest_pk=_latest_graded_pk())
        .filter(pk=F("latest_pk"))
    )


def student_directory() -> QuerySet[User]:
    """Student kartalari uchun enrollment va natija statistikasini tayyorlaydi."""
    active_enrollments = (
        Enrollment.objects.filter(
            status=EnrollmentStatus.ACTIVE,
            course__status=CourseStatus.ACTIVE,
        )
        .select_related("course")
        .order_by("enrolled_at")
    )
    completed_assignments = (
        ExamAttempt.objects.filter(student_id=OuterRef("pk"), status__in=RESULT_STATUSES)
        .order_by()
        .values("student_id")
        .annotate(n=Count("assignment_id", distinct=True))
        .values("n")
    )
    latest_scores = _latest_graded_attempts_for_outer_student()
    average_score = (
        latest_scores.order_by()
        .values("student_id")
        .annotate(value=Avg("percentage"))
        .values("value")
    )
    passed_exams = (
        latest_scores.order_by()
        .values("student_id")
        .annotate(n=Count("pk", filter=Q(passed=True)))
        .values("n")
    )

    return (
        User.objects.filter(role=UserRole.STUDENT)
        .annotate(
            courses_count=_count_for_user(
                Enrollment,
                "student",
                status=EnrollmentStatus.ACTIVE,
                course__status=CourseStatus.ACTIVE,
            ),
            exams_taken=Coalesce(Subquery(completed_assignments, output_field=IntegerField()), 0),
            average_score=Subquery(
                average_score,
                output_field=DecimalField(max_digits=5, decimal_places=2),
            ),
            passed_exams=Coalesce(Subquery(passed_exams, output_field=IntegerField()), 0),
        )
        .prefetch_related(
            Prefetch(
                "enrollments",
                queryset=active_enrollments,
                to_attr="active_enrollments",
            )
        )
    )


def student_directory_summary() -> dict:
    """Student directory tepasidagi umumiy ko'rsatkichlar."""
    student_counts = User.objects.filter(role=UserRole.STUDENT).aggregate(
        total_students=Count("pk"),
        active_students=Count("pk", filter=Q(status=UserStatus.ACTIVE)),
        inactive_students=Count("pk", filter=Q(status=UserStatus.INACTIVE)),
    )
    course_enrollments = Enrollment.objects.filter(
        student__role=UserRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        course__status=CourseStatus.ACTIVE,
    ).count()
    latest_graded = ExamAttempt.objects.filter(
        status=AttemptStatus.GRADED,
        pk=_latest_graded_pk(),
    )
    result_stats = latest_graded.aggregate(
        average_score=Avg("percentage"),
        passed_exams=Count("pk", filter=Q(passed=True)),
    )

    return {
        **student_counts,
        "course_enrollments": course_enrollments,
        "average_score": (
            round(float(result_stats["average_score"]), 2)
            if result_stats["average_score"] is not None
            else None
        ),
        "passed_exams": result_stats["passed_exams"],
    }

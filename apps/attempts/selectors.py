"""O‘qish querylari — attempts."""

from django.db.models import Prefetch, QuerySet

from apps.academics.models import CourseTeacher
from apps.users.choices import UserRole

from .models import ExamAttempt, StudentAnswer, StudentAnswerOption


def attempts_visible_to(user) -> QuerySet[ExamAttempt]:
    """Student — o‘ziniki; Teacher — biriktirilgan kurslar; Super Admin — hammasi."""
    qs = ExamAttempt.objects.select_related("assignment__exam__course", "student")
    if user.role == UserRole.SUPER_ADMIN:
        return qs
    if user.role == UserRole.TEACHER:
        return qs.filter(
            assignment__exam__course_id__in=CourseTeacher.objects.filter(teacher=user).values(
                "course_id"
            )
        )
    if user.role == UserRole.STUDENT:
        return qs.filter(student=user)
    return qs.none()


def with_answers(qs: QuerySet[ExamAttempt]) -> QuerySet[ExamAttempt]:
    return qs.prefetch_related(
        Prefetch(
            "answers",
            queryset=StudentAnswer.objects.select_related("exam_question__question")
            .prefetch_related(
                Prefetch(
                    "selected_options",
                    queryset=StudentAnswerOption.objects.order_by("option__position"),
                ),
                "exam_question__question__options",
            )
            .order_by("exam_question__position"),
        )
    )

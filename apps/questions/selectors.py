"""O‘qish querylari — questions."""

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.academics.models import CourseTeacher
from apps.users.choices import UserRole

from .choices import QuestionStatus, QuestionType
from .models import Question, QuestionOption


def questions_visible_to(user) -> QuerySet[Question]:
    """Savollar banki: Super Admin — hammasi; Teacher — biriktirilgan kurslar; Student — yo‘q."""
    qs = Question.objects.all()
    if user.role == UserRole.SUPER_ADMIN:
        return qs
    if user.role == UserRole.TEACHER:
        return qs.filter(
            course_id__in=CourseTeacher.objects.filter(teacher=user).values("course_id")
        )
    return qs.none()


def question_list(user) -> QuerySet[Question]:
    return questions_visible_to(user).select_related("course", "module", "created_by")


def question_bank_summary(user) -> dict[str, int]:
    """Question bank kartalari uchun role doirasidagi hisoblar."""
    return questions_visible_to(user).aggregate(
        active_questions=Count("pk", filter=Q(status=QuestionStatus.ACTIVE)),
        choice_questions=Count(
            "pk",
            filter=Q(
                status=QuestionStatus.ACTIVE,
                type__in=[QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE],
            ),
        ),
        open_ended=Count(
            "pk",
            filter=Q(status=QuestionStatus.ACTIVE, type=QuestionType.OPEN_ENDED),
        ),
        archived=Count("pk", filter=Q(status=QuestionStatus.ARCHIVED)),
    )


def with_options(qs: QuerySet[Question]) -> QuerySet[Question]:
    return qs.select_related("course", "module", "created_by").prefetch_related(
        Prefetch("options", queryset=QuestionOption.objects.order_by("position"))
    )

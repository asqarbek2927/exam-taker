"""O‘qish querylari — questions."""

from django.db.models import Prefetch, QuerySet

from apps.academics.models import CourseTeacher
from apps.users.choices import UserRole

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
    return questions_visible_to(user).select_related("created_by")


def with_options(qs: QuerySet[Question]) -> QuerySet[Question]:
    return qs.select_related("created_by").prefetch_related(
        Prefetch("options", queryset=QuestionOption.objects.order_by("position"))
    )

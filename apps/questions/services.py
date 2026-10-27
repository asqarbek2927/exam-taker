"""Yozish (write) business logic — questions."""

from decimal import Decimal

from django.db import transaction

from apps.academics.choices import CourseStatus, ModuleStatus
from apps.academics.models import Course, Module
from apps.academics.selectors import has_course_access
from common.exceptions import AccessDeniedError, BusinessRuleError, ConflictError

from .choices import DEFAULT_POINTS, QuestionStatus
from .models import Question, QuestionOption
from .validators import validate_options

LOCKED_MESSAGE = (
    "Savol e’lon qilingan imtihonda ishlatilgan — uni o‘zgartirib bo‘lmaydi. Yangi savol yarating."
)


def _ensure_course_editable(course: Course) -> None:
    if course.status == CourseStatus.ARCHIVED:
        raise BusinessRuleError("Arxivlangan kursga o‘zgartirish kiritib bo‘lmaydi.")


def _ensure_module_usable(course: Course, module: Module) -> None:
    if module.course_id != course.id:
        raise BusinessRuleError("Tanlangan modul bu kursga tegishli emas.")
    if module.status != ModuleStatus.ACTIVE:
        raise BusinessRuleError("Arxivlangan modulga savol biriktirib bo‘lmaydi.")


def _assert_valid_options(question_type: str, options: list[dict]) -> None:
    errors = validate_options(question_type, options)
    if errors:
        raise BusinessRuleError(" ".join(errors))


def _replace_options(question: Question, options: list[dict]) -> None:
    question.options.all().delete()
    QuestionOption.objects.bulk_create(
        QuestionOption(
            question=question,
            text=option["text"].strip(),
            is_correct=bool(option.get("is_correct", False)),
            position=index,
        )
        for index, option in enumerate(options, start=1)
    )


def _is_locked(question: Question) -> bool:
    from apps.exams.selectors import question_is_locked  # lazy: aylanma importdan saqlanish

    return question_is_locked(question)


@transaction.atomic
def create_question(
        *,
        user,
        course: Course,
        module: Module,
        type: str,
        text: str,
        options: list[dict],
        default_points: Decimal | None = None,
) -> Question:
    if not has_course_access(user, course):
        raise AccessDeniedError("Siz bu kursga biriktirilmagansiz.")
    _ensure_course_editable(course)
    _ensure_module_usable(course, module)
    _assert_valid_options(type, options)

    question = Question.objects.create(
        course=course,
        module=module,
        created_by=user,
        type=type,
        text=text.strip(),
        default_points=default_points if default_points is not None else DEFAULT_POINTS[type],
    )
    _replace_options(question, options)
    return question


@transaction.atomic
def update_question(*, question: Question, **fields) -> Question:
    """`fields`: module (Module), type, text, default_points, options (to‘liq almashtiriladi)."""
    if question.status == QuestionStatus.ARCHIVED:
        raise BusinessRuleError("Arxivlangan savolni tahrirlab bo‘lmaydi.")
    _ensure_course_editable(question.course)
    if not fields:
        return question
    if _is_locked(question):
        raise ConflictError(LOCKED_MESSAGE)

    new_type = fields.get("type", question.type)
    if "options" in fields:
        _assert_valid_options(new_type, fields["options"])
    elif new_type != question.type:
        raise BusinessRuleError("Savol turi o‘zgarsa, options ham yuborilishi shart.")

    if "module" in fields:
        _ensure_module_usable(question.course, fields["module"])
        question.module = fields["module"]
    if "type" in fields:
        question.type = new_type
    if "text" in fields:
        question.text = fields["text"].strip()
    if "default_points" in fields:
        question.default_points = fields["default_points"]
    question.save()

    if "options" in fields:
        _replace_options(question, fields["options"])
    return question


def archive_question(question: Question) -> Question:
    if question.status != QuestionStatus.ARCHIVED:
        question.status = QuestionStatus.ARCHIVED
        question.save(update_fields=["status", "updated_at"])
    return question


def restore_question(question: Question) -> Question:
    """Arxivlangan savolni yana question bankda faol qiladi."""
    if question.status == QuestionStatus.ACTIVE:
        return question
    _ensure_course_editable(question.course)
    _ensure_module_usable(question.course, question.module)
    question.status = QuestionStatus.ACTIVE
    question.save(update_fields=["status", "updated_at"])
    return question


def delete_or_archive_question(question: Question) -> bool:
    """Imtihonda ishlatilgan savol — `ARCHIVED`; ishlatilmagan — o‘chiriladi (TZ 8.4).

    Qaytaradi: `True` — arxivlandi, `False` — o‘chirildi.
    """
    _ensure_course_editable(question.course)
    if question.exam_questions.exists():
        archive_question(question)
        return True
    question.delete()
    return False

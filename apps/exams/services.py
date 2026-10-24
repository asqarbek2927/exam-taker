"""Yozish (write) business logic — exams."""

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import TypedDict

from django.db import transaction

from apps.academics.choices import CourseStatus, ModuleStatus
from apps.academics.models import Course, Module
from apps.academics.selectors import has_course_access
from apps.questions.choices import QuestionStatus
from apps.questions.models import Question
from common.exceptions import AccessDeniedError, BusinessRuleError, ConflictError

from .choices import ExamStatus
from .models import Exam, ExamModule, ExamQuestion
from .selectors import exam_has_assignments, exam_is_locked

# Locked imtihonda o‘zgartirib bo‘lmaydigan maydonlar (title/description ruxsat etiladi).
CONTENT_FIELDS = frozenset({"passing_score_percent", "modules", "questions"})
LOCKED_MESSAGE = (
    "Imtihon e’lon qilingan (assignment mavjud) — kontentini o‘zgartirib bo‘lmaydi. "
    "Nusxa (duplicate) yarating."
)


class ExamItem(TypedDict, total=False):
    question: Question
    points: Decimal | None
    position: int | None


def _ensure_course_editable(course: Course) -> None:
    if course.status == CourseStatus.ARCHIVED:
        raise BusinessRuleError("Arxivlangan kursga o‘zgartirish kiritib bo‘lmaydi.")


def _ensure_access(user, course: Course) -> None:
    if not has_course_access(user, course):
        raise AccessDeniedError("Siz bu kursga biriktirilmagansiz.")


def _ensure_unique(ids: Iterable, message: str) -> None:
    ids = list(ids)
    if len(ids) != len(set(ids)):
        raise BusinessRuleError(message)


def _resolve_positions(items: Sequence[ExamItem]) -> list[int]:
    given = [item.get("position") for item in items]
    if all(position is None for position in given):
        return list(range(1, len(items) + 1))
    if any(position is None for position in given):
        raise BusinessRuleError("Barcha savollarga `position` bering yoki hech biriga bermang.")
    if len(set(given)) != len(given):
        raise BusinessRuleError("Savollar `position` qiymatlari takrorlanmasligi kerak.")
    return [int(position) for position in given]


def _validate_content(
    *,
    course: Course,
    modules: Sequence[Module],
    items: Sequence[ExamItem],
    current_module_ids: frozenset = frozenset(),
    current_question_ids: frozenset = frozenset(),
) -> None:
    """TZ 9.4: `Exam.course == Module.course == Question.course`, `Question.module ∈ module_ids`.

    Yangi qo‘shilayotgan modul/savol `ACTIVE` bo‘lishi kerak; mavjudlari (allaqachon
    imtihonda bor) keyin arxivlansa ham tahrir to‘sqinlik qilmaydi.
    """
    _ensure_unique((m.id for m in modules), "Modullar takrorlanmasligi kerak.")
    _ensure_unique((i["question"].id for i in items), "Savollar takrorlanmasligi kerak.")

    for module in modules:
        if module.course_id != course.id:
            raise BusinessRuleError(f"‘{module.title}’ moduli bu kursga tegishli emas.")
        if module.id not in current_module_ids and module.status != ModuleStatus.ACTIVE:
            raise BusinessRuleError(f"‘{module.title}’ moduli arxivlangan.")

    module_ids = {module.id for module in modules}
    for item in items:
        question = item["question"]
        label = question.text[:40]
        if question.course_id != course.id:
            raise BusinessRuleError(f"‘{label}’ savoli bu kursga tegishli emas.")
        if question.id not in current_question_ids and question.status != QuestionStatus.ACTIVE:
            raise BusinessRuleError(f"‘{label}’ savoli arxivlangan.")
        if question.module_id not in module_ids:
            raise BusinessRuleError(f"‘{label}’ savoli tanlangan modullarga tegishli emas.")


def _create_modules(exam: Exam, modules: Iterable[Module]) -> None:
    ExamModule.objects.bulk_create(ExamModule(exam=exam, module=module) for module in modules)


def _create_questions(exam: Exam, items: Sequence[ExamItem]) -> None:
    positions = _resolve_positions(items)
    ExamQuestion.objects.bulk_create(
        ExamQuestion(
            exam=exam,
            question=item["question"],
            points=item.get("points") or item["question"].default_points,
            position=position,
        )
        for item, position in zip(items, positions, strict=True)
    )


# --------------------------------------------------------------------------
# Create / duplicate
# --------------------------------------------------------------------------
@transaction.atomic
def create_exam(
    *,
    user,
    course: Course,
    title: str,
    passing_score_percent: Decimal,
    description: str = "",
    status: str = ExamStatus.DRAFT,
    modules: Sequence[Module] = (),
    questions: Sequence[ExamItem] = (),
) -> Exam:
    _ensure_access(user, course)
    _ensure_course_editable(course)
    if status not in (ExamStatus.DRAFT, ExamStatus.READY):
        raise BusinessRuleError("Yangi imtihon faqat DRAFT yoki READY holatida yaratiladi.")
    if status == ExamStatus.READY and not questions:
        raise BusinessRuleError("READY imtihonda kamida 1 ta savol bo‘lishi kerak.")
    _validate_content(course=course, modules=modules, items=questions)

    exam = Exam.objects.create(
        course=course,
        created_by=user,
        title=title,
        description=description,
        passing_score_percent=passing_score_percent,
        status=status,
    )
    _create_modules(exam, modules)
    _create_questions(exam, questions)
    return exam


@transaction.atomic
def duplicate_exam(*, user, exam: Exam) -> tuple[Exam, list]:
    """Nusxa: yangi muallif, DRAFT. Arxivlangan modul/savollar o‘tkazilmaydi.

    Qaytaradi: `(yangi_exam, o‘tkazib yuborilgan savol ID lari)`.
    """
    _ensure_access(user, exam.course)
    _ensure_course_editable(exam.course)

    modules = [
        exam_module.module
        for exam_module in exam.exam_modules.select_related("module")
        if exam_module.module.status == ModuleStatus.ACTIVE
    ]
    module_ids = {module.id for module in modules}

    items: list[ExamItem] = []
    skipped: list = []
    for exam_question in exam.exam_questions.select_related("question").order_by("position"):
        question = exam_question.question
        if question.status == QuestionStatus.ACTIVE and question.module_id in module_ids:
            items.append({"question": question, "points": exam_question.points, "position": None})
        else:
            skipped.append(question.id)

    copy = Exam.objects.create(
        course=exam.course,
        created_by=user,
        title=f"{exam.title} (nusxa)"[:255],
        description=exam.description,
        passing_score_percent=exam.passing_score_percent,
        status=ExamStatus.DRAFT,
    )
    _create_modules(copy, modules)
    _create_questions(copy, items)
    return copy, skipped


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------
@transaction.atomic
def update_exam(*, exam: Exam, **fields) -> Exam:
    """`fields`: title, description, passing_score_percent, status (DRAFT/READY),
    modules (to‘liq almashtiriladi), questions (to‘liq almashtiriladi; ID lar saqlanadi)."""
    if exam.status == ExamStatus.ARCHIVED:
        raise BusinessRuleError("Arxivlangan imtihonni tahrirlab bo‘lmaydi.")
    _ensure_course_editable(exam.course)
    if not fields:
        return exam

    locked = exam_is_locked(exam)
    if locked and CONTENT_FIELDS & fields.keys():
        raise ConflictError(LOCKED_MESSAGE)

    new_status = fields.get("status", exam.status)
    if new_status not in (ExamStatus.DRAFT, ExamStatus.READY):
        raise BusinessRuleError("Holat faqat DRAFT yoki READY bo‘lishi mumkin (arxiv — alohida).")
    if locked and new_status == ExamStatus.DRAFT and exam.status != ExamStatus.DRAFT:
        raise ConflictError("E’lon qilingan imtihonni DRAFT holatiga qaytarib bo‘lmaydi.")

    existing_modules = {em.module_id: em for em in exam.exam_modules.select_related("module")}
    existing_questions = {
        eq.question_id: eq for eq in exam.exam_questions.select_related("question")
    }

    modules: Sequence[Module] | None = fields.get("modules")
    items: Sequence[ExamItem] | None = fields.get("questions")

    effective_modules = (
        modules if modules is not None else [em.module for em in existing_modules.values()]
    )
    effective_items: Sequence[ExamItem] = (
        items
        if items is not None
        else [
            {"question": eq.question, "points": eq.points, "position": eq.position}
            for eq in existing_questions.values()
        ]
    )

    if modules is not None or items is not None:
        _validate_content(
            course=exam.course,
            modules=effective_modules,
            items=effective_items,
            current_module_ids=frozenset(existing_modules),
            current_question_ids=frozenset(existing_questions),
        )
    if new_status == ExamStatus.READY and not effective_items:
        raise BusinessRuleError("READY imtihonda kamida 1 ta savol bo‘lishi kerak.")

    for name in ("title", "description", "passing_score_percent"):
        if name in fields:
            setattr(exam, name, fields[name])
    exam.status = new_status
    exam.save()

    if modules is not None:
        wanted = {module.id for module in modules}
        ExamModule.objects.filter(exam=exam).exclude(module_id__in=wanted).delete()
        _create_modules(exam, [m for m in modules if m.id not in existing_modules])

    if items is not None:
        _sync_questions(exam, items, existing_questions)
    return exam


def _sync_questions(
    exam: Exam, items: Sequence[ExamItem], existing: dict[object, ExamQuestion]
) -> None:
    """Diff: mavjud `ExamQuestion` lar saqlanadi (attemptlar bog‘lanadi), ortiqchasi o‘chadi."""
    positions = _resolve_positions(items)
    wanted_ids = {item["question"].id for item in items}
    ExamQuestion.objects.filter(exam=exam).exclude(question_id__in=wanted_ids).delete()

    to_update: list[ExamQuestion] = []
    to_create: list[ExamQuestion] = []
    for item, position in zip(items, positions, strict=True):
        question = item["question"]
        current = existing.get(question.id)
        if current is not None:
            current.points = item.get("points") or current.points
            current.position = position
            to_update.append(current)
        else:
            to_create.append(
                ExamQuestion(
                    exam=exam,
                    question=question,
                    points=item.get("points") or question.default_points,
                    position=position,
                )
            )
    ExamQuestion.objects.bulk_update(to_update, ["points", "position"])
    ExamQuestion.objects.bulk_create(to_create)


# --------------------------------------------------------------------------
# Archive / delete
# --------------------------------------------------------------------------
def archive_exam(exam: Exam) -> Exam:
    if exam.status != ExamStatus.ARCHIVED:
        exam.status = ExamStatus.ARCHIVED
        exam.save(update_fields=["status", "updated_at"])
    return exam


def delete_or_archive_exam(exam: Exam) -> bool:
    """Assignment/attempt tarixi bo‘lsa — `ARCHIVED`, aks holda o‘chiriladi (TZ 14).

    Qaytaradi: `True` — arxivlandi, `False` — o‘chirildi.
    """
    _ensure_course_editable(exam.course)
    if exam_has_assignments(exam):
        archive_exam(exam)
        return True
    exam.delete()
    return False

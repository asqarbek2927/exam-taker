"""Yozish (write) business logic — attempts (TZ 11.3–11.6).

Muhim qoidalar:

* Server vaqti — yagona haqiqat manbai (`timezone.now()`).
* Parallel so‘rovlar `select_for_update` bilan ketma-ketlashtiriladi; "bitta faol attempt"
  qoidasi DB constraint (`uniq_active_attempt`) bilan ham himoyalangan.
* Muddati o‘tgan attempt Celery siz yopiladi: *lazy finalization* (har bir so‘rovda) va
  `manage.py finalize_expired_attempts` (cron).
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.assignments.choices import EffectiveStatus
from apps.assignments.models import ExamAssignment
from apps.assignments.selectors import effective_status_of, is_student_eligible
from apps.exams.models import ExamQuestion
from apps.questions.choices import QuestionType
from apps.users.choices import UserStatus
from common.exceptions import AccessDeniedError, BusinessRuleError, ConflictError

from .choices import AttemptStatus, FinalizationReason
from .grading import grade_choice_answer, money, passed, percentage
from .models import ExamAttempt, StudentAnswer, StudentAnswerOption

NOT_STARTABLE_MESSAGES = {
    EffectiveStatus.SCHEDULED: "Imtihon hali boshlanmagan.",
    EffectiveStatus.PAUSED: "Imtihon vaqtincha to‘xtatilgan.",
    EffectiveStatus.COMPLETED: "Imtihon yakunlangan.",
}


def grace() -> timedelta:
    return timedelta(seconds=getattr(settings, "ATTEMPT_GRACE_SECONDS", 10))


def is_expired(attempt: ExamAttempt, now: datetime) -> bool:
    """`deadline_at` + grace dan keyin attempt muddati o‘tgan hisoblanadi."""
    return attempt.status == AttemptStatus.IN_PROGRESS and now > attempt.deadline_at + grace()


def _lock_attempt(attempt_id, *, student=None) -> ExamAttempt:
    queryset = ExamAttempt.objects.select_for_update(of=("self",)).select_related(
        "assignment__exam"
    )
    if student is not None:
        queryset = queryset.filter(student=student)
    attempt = queryset.filter(pk=attempt_id).first()
    if attempt is None:
        raise NotFound("Attempt topilmadi.")
    return attempt


# --------------------------------------------------------------------------
# Grading / finalization
# --------------------------------------------------------------------------
def recalculate_attempt(attempt: ExamAttempt) -> ExamAttempt:
    """`score / percentage / passed / status` ni javoblardan qayta hisoblaydi.

    Submit ham, (keyingi bosqichda) manual grading ham shu funksiyadan foydalanadi.
    Baholanmagan (`points_awarded IS NULL`) javob bor bo‘lsa — natija ochilmaydi.
    """
    exam = attempt.assignment.exam
    total = sum(
        ExamQuestion.objects.filter(exam=exam).values_list("points", flat=True), Decimal("0")
    )
    answers = list(attempt.answers.all())
    if any(answer.points_awarded is None for answer in answers):
        attempt.status = AttemptStatus.PENDING_GRADING
        attempt.score = attempt.percentage = attempt.passed = None
    else:
        score = money(sum((a.points_awarded for a in answers), Decimal("0")))
        attempt.status = AttemptStatus.GRADED
        attempt.score = score
        attempt.percentage = percentage(score, total)
        attempt.passed = passed(score, total, exam.passing_score_percent)
    attempt.save(
        update_fields=[
            "status",
            "score",
            "percentage",
            "passed",
            "submitted_at",
            "finalization_reason",
            "updated_at",
        ]
    )
    return attempt


def _finalize(attempt: ExamAttempt, *, submitted_at: datetime, reason: str) -> ExamAttempt:
    """Attemptni yopadi: javoblarni to‘ldiradi, objective savollarni baholaydi, natijani hisoblaydi.

    Chaqiruvchi `transaction.atomic` ichida va `attempt` qatorini qulflagan bo‘lishi kerak.
    """
    exam_questions = list(
        ExamQuestion.objects.filter(exam_id=attempt.assignment.exam_id)
        .select_related("question")
        .prefetch_related("question__options")
        .order_by("position")
    )
    answers = {
        answer.exam_question_id: answer
        for answer in attempt.answers.prefetch_related("selected_options")
    }

    to_create: list[StudentAnswer] = []
    to_update: list[StudentAnswer] = []
    for exam_question in exam_questions:
        answer = answers.get(exam_question.id)
        is_new = answer is None
        if is_new:
            answer = StudentAnswer(attempt=attempt, exam_question=exam_question, text_answer="")

        question = exam_question.question
        if question.type == QuestionType.OPEN_ENDED:
            if answer.text_answer.strip():
                answer.is_correct, answer.points_awarded = None, None  # manual baholanadi
            else:
                answer.is_correct, answer.points_awarded = False, Decimal("0.00")
        else:
            selected = set() if is_new else {so.option_id for so in answer.selected_options.all()}
            correct = {option.id for option in question.options.all() if option.is_correct}
            answer.is_correct, answer.points_awarded = grade_choice_answer(
                question.type, exam_question.points, correct, selected
            )
        (to_create if is_new else to_update).append(answer)

    StudentAnswer.objects.bulk_create(to_create)
    StudentAnswer.objects.bulk_update(to_update, ["is_correct", "points_awarded"])

    attempt.submitted_at = submitted_at
    attempt.finalization_reason = reason
    return recalculate_attempt(attempt)


def finalize_if_expired(attempt_id, *, now: datetime | None = None) -> bool:
    """Muddati o‘tgan faol attemptni (saqlangan javoblar bilan) avtomatik yopadi."""
    now = now or timezone.now()
    with transaction.atomic():
        attempt = (
            ExamAttempt.objects.select_for_update(of=("self",))
            .select_related("assignment__exam")
            .filter(pk=attempt_id)
            .first()
        )
        if attempt is None or not is_expired(attempt, now):
            return False
        _finalize(
            attempt,
            submitted_at=attempt.deadline_at,
            reason=FinalizationReason.TIMEOUT,
        )
        return True


def finalize_expired_attempts(queryset=None, *, now: datetime | None = None, limit=None) -> int:
    """Muddati o‘tgan barcha faol attemptlarni yopadi. Qaytaradi: yopilganlar soni."""
    now = now or timezone.now()
    queryset = ExamAttempt.objects.all() if queryset is None else queryset
    ids = list(
        queryset.filter(
            status=AttemptStatus.IN_PROGRESS, deadline_at__lt=now - grace()
        ).values_list("id", flat=True)[:limit]
    )
    return sum(finalize_if_expired(attempt_id, now=now) for attempt_id in ids)


# --------------------------------------------------------------------------
# Start
# --------------------------------------------------------------------------
def start_attempt(*, student, assignment_id) -> ExamAttempt:
    """TZ 11.3. `select_for_update` assignmentni bloklaydi: limitni aylanib o‘tib bo‘lmaydi."""
    now = timezone.now()
    # Avval muddati o‘tgan attemptni yopamiz (limit/faol attempt tekshiruvi to‘g‘ri bo‘lishi uchun).
    finalize_expired_attempts(
        ExamAttempt.objects.filter(student=student, assignment_id=assignment_id), now=now
    )

    with transaction.atomic():
        assignment = (
            ExamAssignment.objects.select_for_update(of=("self",))
            .select_related("exam")
            .filter(pk=assignment_id)
            .first()
        )
        if assignment is None:
            raise NotFound("E’lon topilmadi.")
        if student.status != UserStatus.ACTIVE:
            raise AccessDeniedError("Akkaunt faol emas.")
        if not is_student_eligible(assignment, student):
            raise AccessDeniedError("Siz bu imtihonga ruxsat etilmagansiz.")

        status = effective_status_of(assignment, now)
        if status != EffectiveStatus.ACTIVE:
            raise BusinessRuleError(
                NOT_STARTABLE_MESSAGES.get(status, "Imtihonni hozir boshlab bo‘lmaydi.")
            )

        own = ExamAttempt.objects.filter(assignment=assignment, student=student)
        if own.filter(status=AttemptStatus.IN_PROGRESS).exists():
            raise ConflictError("Sizda bu imtihon bo‘yicha tugallanmagan attempt mavjud.")
        used = own.count()
        if assignment.max_attempts is not None and used >= assignment.max_attempts:
            raise ConflictError("Attempt limiti tugagan.")

        deadline = now + timedelta(minutes=assignment.duration_minutes)
        if assignment.end_at is not None:
            deadline = min(deadline, assignment.end_at)
        last = own.aggregate(last=Max("attempt_number"))["last"] or 0
        try:
            with transaction.atomic():
                return ExamAttempt.objects.create(
                    assignment=assignment,
                    student=student,
                    attempt_number=last + 1,
                    started_at=now,
                    deadline_at=deadline,
                )
        except IntegrityError as exc:  # DB constraint — oxirgi himoya
            raise ConflictError("Attempt allaqachon boshlangan.") from exc


# --------------------------------------------------------------------------
# Save answer (autosave)
# --------------------------------------------------------------------------
def _store_answer(
    attempt: ExamAttempt, exam_question_id, option_ids: list | None, text_answer: str | None
) -> StudentAnswer:
    exam_question = (
        ExamQuestion.objects.select_related("question")
        .filter(pk=exam_question_id, exam_id=attempt.assignment.exam_id)
        .first()
    )
    if exam_question is None:
        raise NotFound("Savol bu imtihonga tegishli emas.")
    question = exam_question.question

    chosen: list = []
    if question.type == QuestionType.OPEN_ENDED:
        if option_ids:
            raise BusinessRuleError("OPEN_ENDED savolga `option_ids` yuborilmaydi.")
        if text_answer is None:
            raise BusinessRuleError("OPEN_ENDED savol uchun `text_answer` majburiy.")
    else:
        if text_answer is not None:
            raise BusinessRuleError("Tanlovli savolga `text_answer` yuborilmaydi.")
        if option_ids is None:
            raise BusinessRuleError(
                "Tanlovli savol uchun `option_ids` majburiy (bo‘sh ro‘yxat — tozalash)."
            )
        chosen = list(dict.fromkeys(option_ids))
        valid = set(question.options.values_list("id", flat=True))
        if not set(chosen) <= valid:
            raise BusinessRuleError("Tanlangan option bu savolga tegishli emas.")
        if question.type != QuestionType.MULTIPLE_CHOICE and len(chosen) > 1:
            raise BusinessRuleError("Bu savolda faqat 1 ta option tanlanadi.")

    answer, _ = StudentAnswer.objects.update_or_create(
        attempt=attempt,
        exam_question=exam_question,
        defaults={"text_answer": text_answer or ""},
    )
    answer.selected_options.exclude(option_id__in=chosen).delete()
    existing = set(answer.selected_options.values_list("option_id", flat=True))
    StudentAnswerOption.objects.bulk_create(
        StudentAnswerOption(student_answer=answer, option_id=option_id)
        for option_id in chosen
        if option_id not in existing
    )
    return answer


def save_answer(
    *,
    student,
    attempt_id,
    exam_question_id,
    option_ids: list | None = None,
    text_answer: str | None = None,
) -> StudentAnswer:
    now = timezone.now()
    answer = None
    expired = False
    with transaction.atomic():
        attempt = _lock_attempt(attempt_id, student=student)
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise ConflictError("Attempt allaqachon yakunlangan.")
        if is_expired(attempt, now):
            _finalize(
                attempt,
                submitted_at=attempt.deadline_at,
                reason=FinalizationReason.TIMEOUT,
            )
            expired = True  # xato blokdan KEYIN ko‘tariladi, aks holda yopilish rollback bo‘lardi
        else:
            answer = _store_answer(attempt, exam_question_id, option_ids, text_answer)
    if expired:
        raise ConflictError("Vaqt tugadi — attempt avtomatik yakunlandi.")
    return answer


# --------------------------------------------------------------------------
# Submit
# --------------------------------------------------------------------------
@transaction.atomic
def submit_attempt(*, student, attempt_id) -> ExamAttempt:
    """TZ 11.5. Deadline (+grace) dan keyingi submit — faqat saqlangan javoblar bilan yopiladi."""
    now = timezone.now()
    attempt = _lock_attempt(attempt_id, student=student)
    if attempt.status != AttemptStatus.IN_PROGRESS:
        raise ConflictError("Attempt allaqachon yakunlangan.")
    expired = is_expired(attempt, now)
    submitted_at = attempt.deadline_at if expired else now
    reason = FinalizationReason.TIMEOUT if expired else FinalizationReason.USER_SUBMIT
    return _finalize(attempt, submitted_at=submitted_at, reason=reason)


# --------------------------------------------------------------------------
# Manual grading (TZ 11.7)
# --------------------------------------------------------------------------
@transaction.atomic
def grade_answer(
    *, grader, answer: StudentAnswer, points_awarded: Decimal, teacher_feedback: str | None = None
) -> tuple[StudentAnswer, ExamAttempt]:
    """OPEN_ENDED javobni qo‘lda baholaydi va attempt natijasini qayta hisoblaydi.

    `answer` view tomonidan allaqachon ruxsat tekshiruvidan o‘tgan (queryset scoping).
    Attempt qatori qulflanadi — bir vaqtda ikki teacher baholasa ham natija izchil bo‘ladi.
    Baholangan attemptni qayta baholash (`GRADED` -> `GRADED`) mumkin.
    """
    attempt = _lock_attempt(answer.attempt_id)
    if attempt.status == AttemptStatus.IN_PROGRESS:
        raise ConflictError("Faol (tugallanmagan) attemptni baholab bo‘lmaydi.")

    exam_question = ExamQuestion.objects.select_related("question").get(pk=answer.exam_question_id)
    if exam_question.question.type != QuestionType.OPEN_ENDED:
        raise BusinessRuleError("Faqat OPEN_ENDED savollar qo‘lda baholanadi.")
    points = money(points_awarded)
    if points < 0 or points > exam_question.points:
        raise BusinessRuleError(f"Ball 0 dan {exam_question.points} gacha bo‘lishi kerak.")

    answer = StudentAnswer.objects.select_for_update(of=("self",)).get(pk=answer.pk)
    answer.points_awarded = points
    if teacher_feedback is not None:
        answer.teacher_feedback = teacher_feedback
    answer.graded_by = grader
    answer.graded_at = timezone.now()
    answer.save(
        update_fields=["points_awarded", "teacher_feedback", "graded_by", "graded_at", "updated_at"]
    )
    return answer, recalculate_attempt(attempt)

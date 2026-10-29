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
from random import SystemRandom

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.assignments.choices import EffectiveStatus
from apps.assignments.models import ExamAssignment
from apps.assignments.selectors import effective_status_of, is_student_eligible
from apps.assignments.snapshots import ensure_assignment_snapshot
from apps.audit.choices import AuditAction
from apps.audit.services import record_audit
from apps.exams.models import ExamQuestion
from apps.questions.choices import QuestionType
from apps.users.choices import UserStatus
from common.exceptions import AccessDeniedError, BusinessRuleError, ConflictError

from .choices import AttemptEventAction, AttemptEventType, AttemptStatus, FinalizationReason
from .grading import grade_choice_answer, money, passed, percentage
from .models import (
    AttemptEvent,
    AttemptQuestion,
    AttemptQuestionOption,
    ExamAttempt,
    StudentAnswer,
    StudentAnswerOption,
)

NOT_STARTABLE_MESSAGES = {
    EffectiveStatus.SCHEDULED: "Imtihon hali boshlanmagan.",
    EffectiveStatus.PAUSED: "Imtihon vaqtincha to‘xtatilgan.",
    EffectiveStatus.COMPLETED: "Imtihon yakunlangan.",
}

_random = SystemRandom()
FOCUS_VIOLATION_THRESHOLD = 3
MIN_HIDDEN_SECONDS = 2.5


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
    snapshot = getattr(attempt.assignment, "snapshot", None)
    if snapshot is not None:
        total = sum(snapshot.questions.values_list("points", flat=True), Decimal("0"))
        passing_score = snapshot.passing_score_percent
    else:  # Migratsiyadan oldingi legacy attemptlar uchun fallback.
        exam = attempt.assignment.exam
        total = sum(
            ExamQuestion.objects.filter(exam=exam).values_list("points", flat=True), Decimal("0")
        )
        passing_score = exam.passing_score_percent
    answers = list(attempt.answers.all())
    if any(answer.points_awarded is None for answer in answers):
        attempt.status = AttemptStatus.PENDING_GRADING
        attempt.score = attempt.percentage = attempt.passed = None
    else:
        score = money(sum((a.points_awarded for a in answers), Decimal("0")))
        attempt.status = AttemptStatus.GRADED
        attempt.score = score
        attempt.percentage = percentage(score, total)
        attempt.passed = passed(score, total, passing_score)
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
    delivery_questions = list(
        attempt.delivery_questions.select_related("snapshot_question")
        .prefetch_related("delivery_options__snapshot_option")
        .order_by("position")
    )
    if delivery_questions:
        return _finalize_snapshot_attempt(
            attempt,
            delivery_questions=delivery_questions,
            submitted_at=submitted_at,
            reason=reason,
        )

    # Migratsiyadan oldingi legacy attemptlar uchun fallback.
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
            all_options = {option.id for option in question.options.all()}
            answer.is_correct, answer.points_awarded = grade_choice_answer(
                question.type, exam_question.points, correct, selected, all_options
            )
        (to_create if is_new else to_update).append(answer)

    StudentAnswer.objects.bulk_create(to_create)
    StudentAnswer.objects.bulk_update(to_update, ["is_correct", "points_awarded"])

    attempt.submitted_at = submitted_at
    attempt.finalization_reason = reason
    return recalculate_attempt(attempt)


def _finalize_snapshot_attempt(
    attempt: ExamAttempt,
    *,
    delivery_questions: list[AttemptQuestion],
    submitted_at: datetime,
    reason: str,
) -> ExamAttempt:
    """Attemptni faqat muzlatilgan snapshot answer key asosida baholaydi."""

    answers = {
        answer.attempt_question_id: answer
        for answer in attempt.answers.prefetch_related(
            "selected_options__attempt_option__snapshot_option"
        )
    }
    to_create: list[StudentAnswer] = []
    to_update: list[StudentAnswer] = []
    for delivery_question in delivery_questions:
        snapshot_question = delivery_question.snapshot_question
        answer = answers.get(delivery_question.id)
        is_new = answer is None
        if is_new:
            answer = StudentAnswer(
                attempt=attempt,
                attempt_question=delivery_question,
                text_answer="",
            )

        if snapshot_question.type == QuestionType.OPEN_ENDED:
            if answer.text_answer.strip():
                answer.is_correct, answer.points_awarded = None, None
            else:
                answer.is_correct, answer.points_awarded = False, Decimal("0.00")
        else:
            selected = (
                set()
                if is_new
                else {
                    link.attempt_option.snapshot_option.source_option_id
                    for link in answer.selected_options.all()
                    if link.attempt_option_id is not None
                }
            )
            correct = {
                option.source_option_id
                for option in snapshot_question.options.all()
                if option.is_correct
            }
            all_options = {option.source_option_id for option in snapshot_question.options.all()}
            answer.is_correct, answer.points_awarded = grade_choice_answer(
                snapshot_question.type,
                snapshot_question.points,
                correct,
                selected,
                all_options,
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
                attempt = ExamAttempt.objects.create(
                    assignment=assignment,
                    student=student,
                    attempt_number=last + 1,
                    started_at=now,
                    deadline_at=deadline,
                )
                _create_attempt_delivery(attempt)
                return attempt
        except IntegrityError as exc:  # DB constraint — oxirgi himoya
            raise ConflictError("Attempt allaqachon boshlangan.") from exc


def _create_attempt_delivery(attempt: ExamAttempt) -> None:
    """Savol va option tartibini attempt boshida bir marta saqlaydi."""

    snapshot = ensure_assignment_snapshot(attempt.assignment)
    snapshot_questions = list(snapshot.questions.prefetch_related("options"))
    _random.shuffle(snapshot_questions)
    for question_position, snapshot_question in enumerate(snapshot_questions, start=1):
        attempt_question = AttemptQuestion.objects.create(
            attempt=attempt,
            snapshot_question=snapshot_question,
            position=question_position,
        )
        options = list(snapshot_question.options.all())
        _random.shuffle(options)
        AttemptQuestionOption.objects.bulk_create(
            AttemptQuestionOption(
                attempt_question=attempt_question,
                snapshot_option=option,
                position=option_position,
            )
            for option_position, option in enumerate(options, start=1)
        )


# --------------------------------------------------------------------------
# Browser integrity events
# --------------------------------------------------------------------------
def _safe_event_details(details: dict | None) -> dict:
    details = details or {}
    visibility = details.get("visibility_state")
    return {"visibility_state": visibility} if visibility in {"hidden", "visible"} else {}


def record_attempt_event(
    *, student, attempt_id, event_id, event_type: str, client_at: datetime, details=None
) -> tuple[AttemptEvent, ExamAttempt, str]:
    """Eventni idempotent saqlaydi va authoritative focus counter qaytaradi."""
    now = timezone.now()
    expired = False
    result = None
    with transaction.atomic():
        attempt = _lock_attempt(attempt_id, student=student)
        existing = attempt.events.filter(event_id=event_id).first()
        if existing is not None:
            return existing, attempt, existing.action
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise ConflictError("Attempt allaqachon yakunlangan.")
        if is_expired(attempt, now):
            _finalize(
                attempt,
                submitted_at=attempt.deadline_at,
                reason=FinalizationReason.TIMEOUT,
            )
            expired = True
        else:
            counts_violation = False
            if event_type == AttemptEventType.TAB_VISIBLE:
                previous_focus_event = (
                    attempt.events.filter(
                        type__in=[
                            AttemptEventType.TAB_HIDDEN,
                            AttemptEventType.TAB_VISIBLE,
                        ]
                    )
                    .order_by("-received_at", "-id")
                    .first()
                )
                counts_violation = bool(
                    previous_focus_event
                    and previous_focus_event.type == AttemptEventType.TAB_HIDDEN
                    and (now - previous_focus_event.received_at).total_seconds()
                    >= MIN_HIDDEN_SECONDS
                )

            if counts_violation:
                attempt.focus_violations += 1
                attempt.save(update_fields=["focus_violations", "updated_at"])

            event_action = (
                AttemptEventAction.SUBMIT
                if event_type == AttemptEventType.FULLSCREEN_DECLINED
                or attempt.focus_violations >= FOCUS_VIOLATION_THRESHOLD
                else AttemptEventAction.WARN
            )

            event = AttemptEvent.objects.create(
                attempt=attempt,
                event_id=event_id,
                type=event_type,
                client_at=client_at,
                details=_safe_event_details(details),
                counts_violation=counts_violation,
                focus_violations=attempt.focus_violations,
                action=event_action,
            )

            if event_type == AttemptEventType.FULLSCREEN_DECLINED:
                _finalize(
                    attempt,
                    submitted_at=now,
                    reason=FinalizationReason.FULLSCREEN_DECLINED,
                )
            elif attempt.focus_violations >= FOCUS_VIOLATION_THRESHOLD:
                _finalize(
                    attempt,
                    submitted_at=now,
                    reason=FinalizationReason.FOCUS_LIMIT,
                )

            record_audit(
                actor=student,
                action=AuditAction.ATTEMPT_INTEGRITY_EVENT,
                entity_type="attempt_event",
                entity_id=event.pk,
                metadata={
                    "attempt_id": attempt.pk,
                    "event_id": event.event_id,
                    "event_type": event.type,
                    "counts_violation": event.counts_violation,
                    "focus_violations": event.focus_violations,
                    "finalization_reason": attempt.finalization_reason,
                },
            )
            result = (event, attempt, event.action)
    if expired:
        raise ConflictError("Vaqt tugadi — attempt avtomatik yakunlandi.")
    return result


# --------------------------------------------------------------------------
# Save answer (autosave)
# --------------------------------------------------------------------------
def _store_answer(
    attempt: ExamAttempt,
    exam_question_id,
    option_ids: list | None,
    text_answer: str | None,
    revision: int,
) -> StudentAnswer:
    attempt_question = (
        AttemptQuestion.objects.select_related("snapshot_question")
        .prefetch_related("delivery_options__snapshot_option")
        .filter(
            attempt=attempt,
            snapshot_question__source_exam_question_id=exam_question_id,
        )
        .first()
    )
    if attempt_question is None:
        raise NotFound("Savol bu imtihonga tegishli emas.")
    snapshot_question = attempt_question.snapshot_question

    chosen: list = []
    if snapshot_question.type == QuestionType.OPEN_ENDED:
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
        attempt_options = {
            item.snapshot_option.source_option_id: item
            for item in attempt_question.delivery_options.all()
        }
        valid = set(attempt_options)
        if not set(chosen) <= valid:
            raise BusinessRuleError("Tanlangan option bu savolga tegishli emas.")
        if snapshot_question.type != QuestionType.MULTIPLE_CHOICE and len(chosen) > 1:
            raise BusinessRuleError("Bu savolda faqat 1 ta option tanlanadi.")

    answer = (
        StudentAnswer.objects.filter(attempt=attempt, attempt_question=attempt_question)
        .prefetch_related("selected_options__attempt_option__snapshot_option")
        .first()
    )
    if answer is not None and revision < answer.revision:
        raise ConflictError(f"Stale answer revision; current revision is {answer.revision}.")
    if answer is not None and revision == answer.revision:
        current_options = {
            link.attempt_option.snapshot_option.source_option_id
            for link in answer.selected_options.all()
            if link.attempt_option_id is not None
        }
        same_payload = answer.text_answer == (text_answer or "") and current_options == set(chosen)
        if same_payload:
            return answer
        raise ConflictError(f"Revision {revision} boshqa payload bilan allaqachon saqlangan.")
    if answer is None:
        answer = StudentAnswer.objects.create(
            attempt=attempt,
            attempt_question=attempt_question,
            text_answer=text_answer or "",
            revision=revision,
        )
    else:
        answer.text_answer = text_answer or ""
        answer.revision = revision
        answer.save(update_fields=["text_answer", "revision", "updated_at"])
    chosen_attempt_option_ids = (
        {attempt_options[source_id].id for source_id in chosen} if chosen else set()
    )
    answer.selected_options.exclude(attempt_option_id__in=chosen_attempt_option_ids).delete()
    existing = set(answer.selected_options.values_list("attempt_option_id", flat=True))
    StudentAnswerOption.objects.bulk_create(
        StudentAnswerOption(student_answer=answer, attempt_option_id=attempt_option_id)
        for attempt_option_id in chosen_attempt_option_ids
        if attempt_option_id not in existing
    )
    getattr(answer, "_prefetched_objects_cache", {}).pop("selected_options", None)
    return answer


def save_answer(
    *,
    student,
    attempt_id,
    exam_question_id,
    option_ids: list | None = None,
    text_answer: str | None = None,
    revision: int,
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
            answer = _store_answer(attempt, exam_question_id, option_ids, text_answer, revision)
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

    if answer.attempt_question_id is not None:
        snapshot_question = answer.attempt_question.snapshot_question
        question_type = snapshot_question.type
        max_points = snapshot_question.points
        exam_question = snapshot_question
    else:
        exam_question = ExamQuestion.objects.select_related("question").get(
            pk=answer.exam_question_id
        )
        question_type = exam_question.question.type
        max_points = exam_question.points
    if question_type != QuestionType.OPEN_ENDED:
        raise BusinessRuleError("Faqat OPEN_ENDED savollar qo‘lda baholanadi.")
    points = money(points_awarded)
    if points < 0 or points > max_points:
        raise BusinessRuleError(f"Ball 0 dan {exam_question.points} gacha bo‘lishi kerak.")

    answer = StudentAnswer.objects.select_for_update(of=("self",)).get(pk=answer.pk)
    previous_points = answer.points_awarded
    answer.points_awarded = points
    if teacher_feedback is not None:
        answer.teacher_feedback = teacher_feedback
    answer.graded_by = grader
    answer.graded_at = timezone.now()
    answer.save(
        update_fields=["points_awarded", "teacher_feedback", "graded_by", "graded_at", "updated_at"]
    )
    attempt = recalculate_attempt(attempt)
    record_audit(
        actor=grader,
        action=AuditAction.ANSWER_GRADED,
        entity_type="student_answer",
        entity_id=answer.pk,
        metadata={
            "attempt_id": attempt.pk,
            "assignment_id": attempt.assignment_id,
            "previous_points": previous_points,
            "points_awarded": points,
            "was_regrade": previous_points is not None,
            "attempt_status": attempt.status,
        },
    )
    return answer, attempt

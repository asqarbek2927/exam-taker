"""Results va Dashboard hisob-kitoblari. Statistika DB da saqlanmaydi — manba jadvallardan
hisoblanadi (TZ 12.2). Modelsiz app."""

from datetime import datetime, timedelta

from django.db.models import (
    Avg,
    BooleanField,
    Count,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.academics.choices import CourseStatus, EnrollmentStatus, GroupStatus, ModuleStatus
from apps.academics.models import Course, CourseTeacher, Enrollment, Module, StudyGroup
from apps.assignments.choices import EffectiveStatus
from apps.assignments.models import ExamAssignment, ExamAssignmentRecipient
from apps.assignments.selectors import student_assignments, with_effective_status
from apps.attempts.choices import AttemptStatus, FinalizationReason
from apps.attempts.models import ExamAttempt
from apps.attempts.selectors import attempts_visible_to
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam
from apps.questions.choices import QuestionStatus, QuestionType
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


def result_list(user) -> QuerySet[ExamAttempt]:
    return with_is_latest(results_visible_to(user)).prefetch_related(
        "assignment__assignment_groups__group"
    )


def result_summary(qs: QuerySet[ExamAttempt]) -> dict:
    stats = qs.aggregate(
        submissions=Count("pk"),
        awaiting_review=Count("pk", filter=Q(status=AttemptStatus.PENDING_GRADING)),
        graded=Count("pk", filter=Q(status=AttemptStatus.GRADED)),
        average_score=Avg("percentage", filter=Q(status=AttemptStatus.GRADED)),
    )
    submissions = stats["submissions"]
    graded = stats["graded"]
    return {
        "submissions": submissions,
        "awaiting_review": stats["awaiting_review"],
        "graded": graded,
        "average_score": (
            round(float(stats["average_score"]), 2) if stats["average_score"] is not None else None
        ),
        "grading_progress_percentage": round(graded * 100 / submissions) if submissions else 0,
    }


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


def question_statistics() -> dict:
    """Faol savollar taqsimoti va faol imtihonlarda ishlatilish statistikasi."""
    active_exam_statuses = [ExamStatus.DRAFT, ExamStatus.READY]
    rows = (
        Question.objects.filter(status=QuestionStatus.ACTIVE)
        .values("type")
        .annotate(
            count=Count("pk", distinct=True),
            used=Count(
                "pk",
                filter=Q(exam_questions__exam__status__in=active_exam_statuses),
                distinct=True,
            ),
        )
    )
    by_type = {row["type"]: row for row in rows}
    total = sum(row["count"] for row in by_type.values())
    used = sum(row["used"] for row in by_type.values())

    return {
        "total_questions": total,
        "used_in_exams": used,
        "used_in_exams_percentage": round(used * 100 / total, 2) if total else 0.0,
        "types": [
            {
                "type": question_type.value,
                "label": question_type.label,
                "count": by_type.get(question_type.value, {}).get("count", 0),
                "percentage": round(
                    by_type.get(question_type.value, {}).get("count", 0) * 100 / total, 2
                )
                if total
                else 0.0,
            }
            for question_type in QuestionType
        ],
    }


def course_overview() -> list[dict]:
    """Faol kurslar kesimida enrollment, imtihon va o‘rtacha natija."""
    courses = Course.objects.filter(status=CourseStatus.ACTIVE).annotate(
        students_count=Count(
            "enrollments",
            filter=Q(
                enrollments__status=EnrollmentStatus.ACTIVE,
                enrollments__student__status=UserStatus.ACTIVE,
            ),
            distinct=True,
        ),
        exams_count=Count(
            "exams",
            filter=Q(exams__status__in=[ExamStatus.DRAFT, ExamStatus.READY]),
            distinct=True,
        ),
    )
    latest_graded = only_latest(
        ExamAttempt.objects.filter(status=AttemptStatus.GRADED), [AttemptStatus.GRADED]
    )
    averages = {
        row["assignment__exam__course_id"]: round(float(row["average_score"]), 2)
        for row in latest_graded.values("assignment__exam__course_id").annotate(
            average_score=Avg("percentage")
        )
    }

    return [
        {
            "course_id": course.id,
            "course_name": course.name,
            "students_count": course.students_count,
            "exams_count": course.exams_count,
            "average_score": averages.get(course.id),
        }
        for course in courses.order_by("name", "created_at")
    ]


def dashboard_summary(now: datetime) -> dict:
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    users = User.objects.aggregate(
        total_students=Count("pk", filter=Q(role=UserRole.STUDENT, status=UserStatus.ACTIVE)),
        new_students=Count("pk", filter=Q(role=UserRole.STUDENT, created_at__gte=month_start)),
        total_teachers=Count("pk", filter=Q(role=UserRole.TEACHER, status=UserStatus.ACTIVE)),
        new_teachers=Count("pk", filter=Q(role=UserRole.TEACHER, created_at__gte=month_start)),
    )
    courses = Course.objects.aggregate(
        total=Count("pk"), active=Count("pk", filter=Q(status=CourseStatus.ACTIVE))
    )
    questions = Question.objects.aggregate(
        total=Count("pk", filter=Q(status=QuestionStatus.ACTIVE)),
        added=Count("pk", filter=Q(created_at__gte=month_start)),
    )
    assignments = with_effective_status(
        ExamAssignment.objects.filter(is_archived=False), now
    ).aggregate(
        active=Count("pk", filter=Q(effective_status=EffectiveStatus.ACTIVE)),
        upcoming=Count(
            "pk",
            filter=Q(
                effective_status=EffectiveStatus.SCHEDULED,
                start_at__lte=now + timedelta(days=7),
            ),
        ),
    )
    return {
        "students": {
            "total": users["total_students"],
            "added_this_month": users["new_students"],
        },
        "teachers": {
            "total": users["total_teachers"],
            "added_this_month": users["new_teachers"],
        },
        "courses": courses,
        "questions": {
            "total": questions["total"],
            "added_this_month": questions["added"],
        },
        "exams": {
            "total": Exam.objects.exclude(status=ExamStatus.ARCHIVED).count(),
            "active_assignments": assignments["active"],
        },
        "upcoming_assignments": {
            "next_7_days": assignments["upcoming"],
        },
    }


def recent_exams(limit: int = 5) -> list[dict]:
    exams = Exam.objects.select_related("course", "created_by").order_by("-created_at")[:limit]
    return [
        {
            "id": exam.id,
            "title": exam.title,
            "course_id": exam.course_id,
            "course_name": exam.course.name,
            "created_by_id": exam.created_by_id,
            "created_by_name": exam.created_by.full_name,
            "created_at": exam.created_at,
            "status": exam.status,
        }
        for exam in exams
    ]


def recent_results(limit: int = 5) -> list[dict]:
    attempts = (
        ExamAttempt.objects.filter(
            status=AttemptStatus.GRADED,
            submitted_at__isnull=False,
            percentage__isnull=False,
        )
        .select_related("student", "assignment__exam__course")
        .order_by("-submitted_at")[:limit]
    )
    return [
        {
            "attempt_id": attempt.id,
            "student_id": attempt.student_id,
            "student_name": attempt.student.full_name,
            "student_avatar_url": attempt.student.avatar_url,
            "exam_title": attempt.assignment.exam.title,
            "course_name": attempt.assignment.exam.course.name,
            "submitted_at": attempt.submitted_at,
            "percentage": float(attempt.percentage),
            "passed": attempt.passed,
        }
        for attempt in attempts
    ]


def exam_activity(now: datetime, days: int = 7) -> dict:
    today = timezone.localdate(now)
    start = today - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    completed = ExamAttempt.objects.filter(status__in=RESULT_STATUSES)
    rows = (
        completed.filter(submitted_at__date__gte=previous_start, submitted_at__date__lte=today)
        .annotate(day=TruncDate("submitted_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(count=Count("pk"))
    )
    counts = {row["day"]: row["count"] for row in rows}
    items = [
        {
            "date": start + timedelta(days=index),
            "completed_attempts": counts.get(start + timedelta(days=index), 0),
        }
        for index in range(days)
    ]
    current_total = sum(item["completed_attempts"] for item in items)
    previous_total = sum(
        counts.get(previous_start + timedelta(days=index), 0) for index in range(days)
    )
    change = (
        round((current_total - previous_total) * 100 / previous_total, 2)
        if previous_total
        else None
    )
    return {
        "period_days": days,
        "items": items,
        "current_total": current_total,
        "previous_total": previous_total,
        "change_percentage": change,
    }


def exam_statistics() -> dict:
    completed = ExamAttempt.objects.filter(status__in=RESULT_STATUSES)
    latest_graded = only_latest(
        completed.filter(status=AttemptStatus.GRADED), [AttemptStatus.GRADED]
    )
    graded = latest_graded.aggregate(
        average=Avg("percentage"),
        total=Count("pk"),
        passed=Count("pk", filter=Q(passed=True)),
    )

    completed_attempt = ExamAttempt.objects.filter(
        assignment_id=OuterRef("assignment_id"),
        student_id=OuterRef("student_id"),
        status__in=RESULT_STATUSES,
    )
    recipients = ExamAssignmentRecipient.objects.all()
    assigned_recipients = recipients.count()
    completed_recipients = recipients.filter(Exists(completed_attempt)).count()

    attempt_counts = completed.aggregate(
        completed=Count("pk"),
        tracked=Count("pk", filter=Q(finalization_reason__isnull=False)),
        on_time=Count(
            "pk",
            filter=Q(
                finalization_reason=FinalizationReason.USER_SUBMIT,
                submitted_at__lte=F("deadline_at"),
            ),
        ),
    )

    return {
        "completed_attempts": attempt_counts["completed"],
        "graded_attempts": graded["total"],
        "passed_attempts": graded["passed"],
        "pass_rate": round(graded["passed"] * 100 / graded["total"], 2)
        if graded["total"]
        else None,
        "average_score": round(float(graded["average"]), 2) if graded["total"] else None,
        "assigned_recipients": assigned_recipients,
        "completed_recipients": completed_recipients,
        "completion_rate": round(completed_recipients * 100 / assigned_recipients, 2)
        if assigned_recipients
        else None,
        "tracked_submissions": attempt_counts["tracked"],
        "on_time_submissions": attempt_counts["on_time"],
        "on_time_submission_rate": round(
            attempt_counts["on_time"] * 100 / attempt_counts["tracked"], 2
        )
        if attempt_counts["tracked"]
        else None,
    }


def platform_activity(limit: int = 10) -> list[dict]:
    events = []
    for user in User.objects.filter(role=UserRole.TEACHER).order_by("-created_at")[:limit]:
        events.append(
            {
                "type": "TEACHER_JOINED",
                "title": "New teacher joined",
                "description": user.full_name,
                "occurred_at": user.created_at,
            }
        )
    for exam in Exam.objects.select_related("course").order_by("-created_at")[:limit]:
        events.append(
            {
                "type": "EXAM_CREATED",
                "title": f"{exam.title} created",
                "description": exam.course.name,
                "occurred_at": exam.created_at,
            }
        )
    published = (
        ExamAssignment.objects.exclude(published_at=None)
        .select_related("exam__course")
        .order_by("-published_at")[:limit]
    )
    for assignment in published:
        events.append(
            {
                "type": "ASSIGNMENT_PUBLISHED",
                "title": f"{assignment.exam.title} published",
                "description": assignment.exam.course.name,
                "occurred_at": assignment.published_at,
            }
        )
    for question in Question.objects.select_related("course").order_by("-created_at")[:limit]:
        events.append(
            {
                "type": "QUESTION_CREATED",
                "title": "Question bank updated",
                "description": f"{question.course.name} · {question.get_type_display()}",
                "occurred_at": question.created_at,
            }
        )
    results = (
        ExamAttempt.objects.filter(
            status=AttemptStatus.GRADED,
            submitted_at__isnull=False,
            percentage__isnull=False,
        )
        .select_related("student", "assignment__exam")
        .order_by("-submitted_at")[:limit]
    )
    for attempt in results:
        events.append(
            {
                "type": "RESULT_RECORDED",
                "title": "New result recorded",
                "description": (
                    f"{attempt.student.full_name} · {attempt.assignment.exam.title} · "
                    f"{float(attempt.percentage):g}%"
                ),
                "occurred_at": attempt.submitted_at,
            }
        )
    return sorted(events, key=lambda event: event["occurred_at"], reverse=True)[:limit]


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def admin_dashboard(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    statistics = exam_statistics()
    summary = dashboard_summary(now)
    assignments = ExamAssignment.objects.filter(is_archived=False)
    return {
        "total_students": summary["students"]["total"],
        "total_teachers": summary["teachers"]["total"],
        "total_courses": summary["courses"]["active"],
        "total_modules": Module.objects.filter(status=ModuleStatus.ACTIVE).count(),
        "total_questions": summary["questions"]["total"],
        "total_exams": summary["exams"]["total"],
        "active_assignments": summary["exams"]["active_assignments"],
        "completed_assignments": _count_effective(assignments, EffectiveStatus.COMPLETED, now),
        "average_score": statistics["average_score"],
        "pass_rate": statistics["pass_rate"],
        "question_statistics": question_statistics(),
        "course_overview": course_overview(),
        "summary": summary,
        "recent_exams": recent_exams(),
        "recent_results": recent_results(),
        "exam_activity": exam_activity(now),
        "exam_statistics": statistics,
        "platform_activity": platform_activity(),
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
        "my_groups": StudyGroup.objects.filter(
            course_id__in=course_ids, status=GroupStatus.ACTIVE
        ).count(),
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
            ExamAssignment.objects.filter(published_by=teacher, is_archived=False),
            EffectiveStatus.ACTIVE,
            now,
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

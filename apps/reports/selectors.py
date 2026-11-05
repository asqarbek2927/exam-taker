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
    Prefetch,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.academics.choices import (
    CourseStatus,
    CourseTeacherType,
    EnrollmentStatus,
    GroupStatus,
    ModuleStatus,
)
from apps.academics.models import (
    Course,
    CourseTeacher,
    Enrollment,
    GroupStudent,
    Module,
    StudyGroup,
)
from apps.assignments.choices import EffectiveStatus
from apps.assignments.models import ExamAssignment, ExamAssignmentRecipient
from apps.assignments.selectors import staff_visible, student_assignments, with_effective_status
from apps.attempts.choices import AttemptStatus, FinalizationReason
from apps.attempts.models import ExamAttempt
from apps.attempts.selectors import attempts_visible_to
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam
from apps.questions.choices import QuestionStatus, QuestionType
from apps.questions.models import Question
from apps.users.choices import EDUCATOR_ROLES, UserRole, UserStatus
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
        new_students=Count(
            "pk",
            filter=Q(
                role=UserRole.STUDENT,
                status__in=[UserStatus.ACTIVE, UserStatus.INACTIVE],
                created_at__gte=month_start,
            ),
        ),
        total_teachers=Count("pk", filter=Q(role__in=EDUCATOR_ROLES, status=UserStatus.ACTIVE)),
        new_teachers=Count(
            "pk",
            filter=Q(
                role__in=EDUCATOR_ROLES,
                status__in=[UserStatus.ACTIVE, UserStatus.INACTIVE],
                created_at__gte=month_start,
            ),
        ),
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
    previous_items = [
        {
            "date": previous_start + timedelta(days=index),
            "completed_attempts": counts.get(previous_start + timedelta(days=index), 0),
        }
        for index in range(days)
    ]
    current_total = sum(item["completed_attempts"] for item in items)
    previous_total = sum(item["completed_attempts"] for item in previous_items)
    change = (
        round((current_total - previous_total) * 100 / previous_total, 2)
        if previous_total
        else None
    )
    return {
        "period_days": days,
        "items": items,
        "previous_items": previous_items,
        "current_total": current_total,
        "previous_total": previous_total,
        "change_percentage": change,
    }


def dashboard_comparison(now: datetime, days: int = 30) -> dict:
    """Joriy davrni undan oldingi teng davr bilan aniq nomlangan metrikalarda solishtiradi."""
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    students = User.objects.filter(
        role=UserRole.STUDENT,
        status__in=[UserStatus.ACTIVE, UserStatus.INACTIVE],
    )
    student_counts = students.aggregate(
        current=Count(
            "pk", filter=Q(created_at__gte=current_start, created_at__lte=now)
        ),
        previous=Count(
            "pk", filter=Q(created_at__gte=previous_start, created_at__lt=current_start)
        ),
    )
    current_students = student_counts["current"]
    previous_students = student_counts["previous"]
    student_change = (
        round((current_students - previous_students) * 100 / previous_students, 2)
        if previous_students
        else None
    )

    graded = ExamAttempt.objects.filter(
        status=AttemptStatus.GRADED,
        submitted_at__isnull=False,
        percentage__isnull=False,
    )
    score_averages = graded.aggregate(
        current=Avg(
            "percentage", filter=Q(submitted_at__gte=current_start, submitted_at__lte=now)
        ),
        previous=Avg(
            "percentage",
            filter=Q(submitted_at__gte=previous_start, submitted_at__lt=current_start),
        ),
    )
    current_average = score_averages["current"]
    previous_average = score_averages["previous"]
    current_average = round(float(current_average), 2) if current_average is not None else None
    previous_average = round(float(previous_average), 2) if previous_average is not None else None
    score_change = (
        round(current_average - previous_average, 2)
        if current_average is not None and previous_average is not None
        else None
    )

    return {
        "period_days": days,
        "current_period": {"start_at": current_start, "end_at": now},
        "previous_period": {"start_at": previous_start, "end_at": current_start},
        "student_registrations": {
            "current_period": current_students,
            "previous_period": previous_students,
            "change_percentage": student_change,
        },
        "average_score": {
            "current_period": current_average,
            "previous_period": previous_average,
            "change_points": score_change,
        },
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
    for user in User.objects.filter(
        role__in=EDUCATOR_ROLES,
        status__in=[UserStatus.ACTIVE, UserStatus.INACTIVE],
    ).order_by("-created_at")[:limit]:
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
        "total_courses": summary["courses"]["total"],
        "active_courses": summary["courses"]["active"],
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
        "comparison": dashboard_comparison(now),
        "exam_statistics": statistics,
        "platform_activity": platform_activity(),
    }


def _result_activity(attempts: QuerySet[ExamAttempt], now: datetime, days: int = 7) -> dict:
    today = timezone.localdate(now)
    current_start = today - timedelta(days=days - 1)
    previous_start = current_start - timedelta(days=days)
    rows = (
        attempts.filter(
            status=AttemptStatus.GRADED,
            submitted_at__date__gte=previous_start,
            submitted_at__date__lte=today,
            percentage__isnull=False,
        )
        .annotate(day=TruncDate("submitted_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(average_score=Avg("percentage"), graded_attempts=Count("pk"))
    )
    by_day = {row["day"]: row for row in rows}

    def build(start):
        return [
            {
                "date": start + timedelta(days=index),
                "average_score": (
                    round(float(by_day[day]["average_score"]), 2) if day in by_day else None
                ),
                "graded_attempts": by_day.get(day, {}).get("graded_attempts", 0),
            }
            for index in range(days)
            for day in [start + timedelta(days=index)]
        ]

    return {
        "period_days": days,
        "items": build(current_start),
        "previous_items": build(previous_start),
    }


def _teacher_assignments(teacher, now: datetime) -> QuerySet[ExamAssignment]:
    """Dashboard uchun teacher ko‘ra oladigan, arxivlanmagan assignmentlar."""
    return with_effective_status(staff_visible(teacher).filter(is_archived=False), now)


def _teacher_upcoming_exams(
    assignments: QuerySet[ExamAssignment], limit: int = 5
) -> list[dict]:
    assignments = (
        assignments.filter(
            effective_status__in=[EffectiveStatus.ACTIVE, EffectiveStatus.SCHEDULED]
        )
        .select_related("exam__course")
        .annotate(students_count=Count("recipients", distinct=True))
        .prefetch_related("assignment_groups__group")
        .order_by("start_at")[:limit]
    )
    return [
        {
            "assignment_id": item.id,
            "exam_id": item.exam_id,
            "exam_title": item.exam.title,
            "course_id": item.exam.course_id,
            "course_name": item.exam.course.name,
            "groups": [
                {"id": link.group_id, "name": link.group.name}
                for link in item.assignment_groups.all()
            ],
            "start_at": item.start_at,
            "duration_minutes": item.duration_minutes,
            "students_count": item.students_count,
            "status": item.effective_status,
        }
        for item in assignments
    ]


def _teacher_course_cards(teacher, attempts: QuerySet[ExamAttempt]) -> list[dict]:
    courses = (
        Course.objects.filter(
            status=CourseStatus.ACTIVE,
            course_teachers__teacher=teacher,
        )
        .annotate(
            groups_count=Count(
                "groups", filter=Q(groups__status=GroupStatus.ACTIVE), distinct=True
            ),
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
                filter=~Q(exams__status=ExamStatus.ARCHIVED),
                distinct=True,
            ),
        )
        .distinct()
        .order_by("name", "created_at")
    )
    latest = only_latest(
        attempts.filter(status=AttemptStatus.GRADED, percentage__isnull=False),
        [AttemptStatus.GRADED],
    )
    averages = {
        row["assignment__exam__course_id"]: round(float(row["average_score"]), 2)
        for row in latest.values("assignment__exam__course_id").annotate(
            average_score=Avg("percentage")
        )
    }
    return [
        {
            "course_id": course.id,
            "course_name": course.name,
            "groups_count": course.groups_count,
            "students_count": course.students_count,
            "exams_count": course.exams_count,
            "average_score": averages.get(course.id),
        }
        for course in courses
    ]


def _teacher_recent_results(attempts: QuerySet[ExamAttempt], limit: int = 5) -> list[dict]:
    rows = attempts.filter(
        status=AttemptStatus.GRADED,
        submitted_at__isnull=False,
    ).order_by("-submitted_at")[:limit]
    return [
        {
            "attempt_id": item.id,
            "student_id": item.student_id,
            "student_name": item.student.full_name,
            "exam_title": item.assignment.exam.title,
            "course_name": item.assignment.exam.course.name,
            "percentage": float(item.percentage) if item.percentage is not None else None,
            "status": item.status,
            "submitted_at": item.submitted_at,
        }
        for item in rows
    ]


def _teacher_grading_queue(attempts: QuerySet[ExamAttempt], limit: int = 5) -> list[dict]:
    rows = (
        attempts.filter(status=AttemptStatus.PENDING_GRADING, submitted_at__isnull=False)
        .annotate(
            pending_answers_count=Count(
                "answers", filter=Q(answers__points_awarded__isnull=True), distinct=True
            )
        )
        .order_by("submitted_at")[:limit]
    )
    return [
        {
            "attempt_id": item.id,
            "student_id": item.student_id,
            "student_name": item.student.full_name,
            "exam_title": item.assignment.exam.title,
            "course_name": item.assignment.exam.course.name,
            "pending_answers_count": item.pending_answers_count,
            "submitted_at": item.submitted_at,
        }
        for item in rows
    ]


def teacher_dashboard(teacher, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    course_ids = list(
        CourseTeacher.objects.filter(
            teacher=teacher, course__status=CourseStatus.ACTIVE
        ).values_list("course_id", flat=True)
    )
    attempts = attempts_visible_to(teacher)
    assignments = _teacher_assignments(teacher, now)
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
        "active_assignments": assignments.filter(
            effective_status=EffectiveStatus.ACTIVE
        ).count(),
        "pending_grading": attempts.filter(status=AttemptStatus.PENDING_GRADING).count(),
        "average_student_score": average,
        "upcoming_exams": _teacher_upcoming_exams(assignments),
        "result_activity": _result_activity(attempts, now),
        "course_cards": _teacher_course_cards(teacher, attempts),
        "recent_results": _teacher_recent_results(attempts),
        "grading_queue": _teacher_grading_queue(attempts),
    }


def _student_upcoming_exams(assignments, limit: int = 5) -> list[dict]:
    items = assignments.filter(
        Q(effective_status=EffectiveStatus.SCHEDULED)
        | (
            Q(effective_status=EffectiveStatus.ACTIVE)
            & (
                Q(active_attempt_id__isnull=False)
                | Q(max_attempts__isnull=True)
                | Q(attempts_used__lt=F("max_attempts"))
            )
        )
    ).order_by("start_at")[:limit]
    return [
        {
            "assignment_id": item.id,
            "exam_title": item.exam.title,
            "course_id": item.exam.course_id,
            "course_name": item.exam.course.name,
            "start_at": item.start_at,
            "duration_minutes": item.duration_minutes,
            "questions_count": item.questions_count,
            "status": item.effective_status,
        }
        for item in items
    ]


def _student_course_progress(student, assignments) -> list[dict]:
    enrollments = list(
        Enrollment.objects.filter(
            student=student,
            status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED],
        )
        .select_related("course")
        .order_by("course__name")
    )
    course_ids = [item.course_id for item in enrollments]
    main_teachers = {
        row.course_id: row.teacher
        for row in CourseTeacher.objects.filter(
            course_id__in=course_ids,
            type=CourseTeacherType.MAIN,
            teacher__status__in=[UserStatus.ACTIVE, UserStatus.INACTIVE],
        )
        .select_related("teacher")
        .order_by("assigned_at")
    }
    assignment_items = list(assignments.order_by("start_at"))
    completed_ids = set(
        ExamAttempt.objects.filter(student=student, status__in=RESULT_STATUSES).values_list(
            "assignment_id", flat=True
        )
    )
    by_course: dict = {course_id: [] for course_id in course_ids}
    for item in assignment_items:
        by_course.setdefault(item.exam.course_id, []).append(item)

    result = []
    for enrollment in enrollments:
        course_assignments = by_course.get(enrollment.course_id, [])
        completed = sum(item.id in completed_ids for item in course_assignments)
        total = len(course_assignments)
        next_item = next(
            (
                item
                for item in course_assignments
                if item.id not in completed_ids
                and item.effective_status in [EffectiveStatus.ACTIVE, EffectiveStatus.SCHEDULED]
            ),
            None,
        )
        teacher = main_teachers.get(enrollment.course_id)
        result.append(
            {
                "course_id": enrollment.course_id,
                "course_name": enrollment.course.name,
                "teacher": (
                    {"id": teacher.id, "full_name": teacher.full_name} if teacher else None
                ),
                "progress_percentage": round(completed * 100 / total, 2) if total else 0.0,
                "completed_assignments": completed,
                "total_assignments": total,
                "next_step": (
                    {
                        "assignment_id": next_item.id,
                        "exam_title": next_item.exam.title,
                        "start_at": next_item.start_at,
                        "status": next_item.effective_status,
                    }
                    if next_item
                    else None
                ),
            }
        )
    return result


def _student_study_groups(student) -> list[dict]:
    groups = (
        StudyGroup.objects.filter(
            status=GroupStatus.ACTIVE,
            course__status=CourseStatus.ACTIVE,
            group_students__student=student,
        )
        .select_related("course", "main_teacher", "support_teacher")
        .prefetch_related(
            Prefetch(
                "group_students",
                queryset=GroupStudent.objects.filter(student__status=UserStatus.ACTIVE)
                .select_related("student")
                .order_by("student__full_name"),
                to_attr="active_memberships",
            )
        )
        .distinct()
        .order_by("name")
    )
    result = []
    for group in groups:
        classmates = [
            item.student for item in group.active_memberships if item.student_id != student.id
        ]
        teachers = [teacher for teacher in [group.main_teacher, group.support_teacher] if teacher]
        result.append(
            {
                "group_id": group.id,
                "group_name": group.name,
                "course_id": group.course_id,
                "course_name": group.course.name,
                "teachers": [
                    {"id": teacher.id, "full_name": teacher.full_name} for teacher in teachers
                ],
                "classmates_count": len(classmates),
                "classmates": [
                    {"id": classmate.id, "full_name": classmate.full_name}
                    for classmate in classmates[:5]
                ],
            }
        )
    return result


def _student_recent_results(own_attempts: QuerySet[ExamAttempt], limit: int = 5) -> list[dict]:
    rows = only_latest(
        own_attempts.filter(status__in=RESULT_STATUSES, submitted_at__isnull=False)
    ).order_by("-submitted_at")[:limit]
    return [
        {
            "attempt_id": item.id,
            "exam_title": item.assignment.exam.title,
            "course_id": item.assignment.exam.course_id,
            "course_name": item.assignment.exam.course.name,
            "percentage": float(item.percentage) if item.percentage is not None else None,
            "status": item.status,
            "submitted_at": item.submitted_at,
        }
        for item in rows
    ]


def _student_recent_activity(own_attempts: QuerySet[ExamAttempt], limit: int = 10) -> list[dict]:
    events = []
    for item in own_attempts.order_by("-started_at")[:limit]:
        exam_title = item.assignment.exam.title
        events.append(
            {
                "type": "ATTEMPT_STARTED",
                "description": f"{exam_title} imtihoni boshlandi",
                "occurred_at": item.started_at,
            }
        )
        if item.submitted_at is not None:
            events.append(
                {
                    "type": "RESULT_SUBMITTED",
                    "description": f"{exam_title} imtihoni topshirildi",
                    "occurred_at": item.submitted_at,
                }
            )
    return sorted(events, key=lambda event: event["occurred_at"], reverse=True)[:limit]


def student_dashboard(student, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    own_attempts = attempts_visible_to(student)
    average, _ = score_stats(own_attempts)

    latest_graded = only_latest(
        own_attempts.filter(status=AttemptStatus.GRADED), [AttemptStatus.GRADED]
    )
    assignments = student_assignments(student, now)
    available = (
        assignments
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
        "upcoming_exams": _student_upcoming_exams(assignments),
        "course_progress": _student_course_progress(student, assignments),
        "study_groups": _student_study_groups(student),
        "recent_results": _student_recent_results(own_attempts),
        "recent_activity": _student_recent_activity(own_attempts),
    }

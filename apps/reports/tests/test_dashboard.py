from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.choices import CourseStatus, EnrollmentStatus, GroupStatus, ModuleStatus
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    ModuleFactory,
    StudyGroupFactory,
)
from apps.assignments.choices import AssignmentStatus
from apps.assignments.models import ExamAssignmentRecipient
from apps.assignments.tests.factories import AssignmentFactory
from apps.attempts.choices import FinalizationReason
from apps.attempts.tests.factories import AttemptFactory
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory, ExamQuestionFactory
from apps.questions.choices import QuestionStatus, QuestionType
from apps.questions.tests.factories import QuestionFactory
from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

ADMIN, TEACHER, STUDENT = (f"/api/v1/{role}/dashboard" for role in ("admin", "teacher", "student"))


def graded(assignment, student, number, percentage, passed):
    return AttemptFactory(
        assignment=assignment,
        student=student,
        attempt_number=number,
        status="GRADED",
        percentage=percentage,
        score=percentage / 10,
        passed=passed,
        submitted_at=timezone.now(),
        finalization_reason=FinalizationReason.USER_SUBMIT,
    )


# ------------------------------- permissions -------------------------------
@pytest.mark.parametrize(
    ("url", "allowed"), [(ADMIN, "admin"), (TEACHER, "teacher"), (STUDENT, "student")]
)
def test_each_dashboard_is_role_specific(request, auth_client, api_client, url, allowed):
    users = {name: request.getfixturevalue(name) for name in ("admin", "teacher", "student")}
    for name, user in users.items():
        expected = 200 if name == allowed else 403
        assert auth_client(user).get(url).status_code == expected, (url, name)
    assert api_client.get(url).status_code == 401


# ------------------------------- empty state -------------------------------
def test_empty_state_returns_zeros_and_nulls(auth_client, admin, teacher, student):
    admin_body = auth_client(admin).get(ADMIN).json()
    summary = admin_body.pop("summary")
    recent_exams = admin_body.pop("recent_exams")
    recent_results = admin_body.pop("recent_results")
    activity = admin_body.pop("exam_activity")
    exam_stats = admin_body.pop("exam_statistics")
    platform_events = admin_body.pop("platform_activity")
    assert admin_body == {
        "total_students": 1,
        "total_teachers": 1,
        "total_courses": 0,
        "total_modules": 0,
        "total_questions": 0,
        "total_exams": 0,
        "active_assignments": 0,
        "completed_assignments": 0,
        "average_score": None,
        "pass_rate": None,
        "question_statistics": {
            "total_questions": 0,
            "used_in_exams": 0,
            "used_in_exams_percentage": 0.0,
            "types": [
                {"type": "SINGLE_CHOICE", "label": "Single choice", "count": 0, "percentage": 0.0},
                {
                    "type": "MULTIPLE_CHOICE",
                    "label": "Multiple choice",
                    "count": 0,
                    "percentage": 0.0,
                },
                {"type": "TRUE_FALSE", "label": "True / False", "count": 0, "percentage": 0.0},
                {"type": "OPEN_ENDED", "label": "Open ended", "count": 0, "percentage": 0.0},
            ],
        },
        "course_overview": [],
    }
    assert summary == {
        "students": {"total": 1, "added_this_month": 1},
        "teachers": {"total": 1, "added_this_month": 1},
        "courses": {"total": 0, "active": 0},
        "questions": {"total": 0, "added_this_month": 0},
        "exams": {"total": 0, "active_assignments": 0},
        "upcoming_assignments": {"next_7_days": 0},
    }
    assert recent_exams == [] and recent_results == []
    assert activity["period_days"] == 7
    assert len(activity["items"]) == 7
    assert activity["current_total"] == activity["previous_total"] == 0
    assert activity["change_percentage"] is None
    assert exam_stats == {
        "completed_attempts": 0,
        "graded_attempts": 0,
        "passed_attempts": 0,
        "pass_rate": None,
        "average_score": None,
        "assigned_recipients": 0,
        "completed_recipients": 0,
        "completion_rate": None,
        "tracked_submissions": 0,
        "on_time_submissions": 0,
        "on_time_submission_rate": None,
    }
    assert [event["type"] for event in platform_events] == ["TEACHER_JOINED"]
    assert auth_client(teacher).get(TEACHER).json() == {
        "my_courses": 0,
        "my_groups": 0,
        "my_students": 0,
        "my_questions": 0,
        "my_exams": 0,
        "active_assignments": 0,
        "pending_grading": 0,
        "average_student_score": None,
    }
    assert auth_client(student).get(STUDENT).json() == {
        "my_courses": 0,
        "available_exams": 0,
        "completed_exams": 0,
        "average_score": None,
        "passed_exams": 0,
    }


# ------------------------------- admin -------------------------------
def test_admin_dashboard_counts_ignore_inactive_and_archived(auth_client, admin):
    client = auth_client(admin)
    before = client.get(ADMIN).json()

    StudentFactory.create_batch(2)
    StudentFactory(status=UserStatus.INACTIVE)  # sanalmaydi
    author = TeacherFactory()
    TeacherFactory(status=UserStatus.INACTIVE)  # sanalmaydi
    CourseFactory()
    CourseFactory(status=CourseStatus.ARCHIVED)  # sanalmaydi
    course = CourseFactory()
    module = ModuleFactory(course=course)
    ModuleFactory(course=course, status=ModuleStatus.ARCHIVED)  # sanalmaydi
    QuestionFactory(course=course, module=module, created_by=author)
    QuestionFactory(course=course, module=module, created_by=author, status=QuestionStatus.ARCHIVED)
    ExamFactory(course=course, created_by=author)
    ExamFactory(course=course, created_by=author, status=ExamStatus.ARCHIVED)  # sanalmaydi

    after = client.get(ADMIN).json()
    delta = {key: after[key] - before[key] for key in before if key.startswith("total_")}
    assert delta["total_students"] == 2
    assert delta["total_teachers"] == 1
    assert delta["total_courses"] == 2
    assert delta["total_modules"] == 1
    assert delta["total_questions"] == 1
    assert delta["total_exams"] == 1


def test_admin_assignment_counts_use_effective_status(auth_client, admin):
    now = timezone.now()
    day = timedelta(days=1)
    AssignmentFactory()  # ACTIVE
    AssignmentFactory(start_at=now + day, end_at=None)  # SCHEDULED
    AssignmentFactory(start_at=now - 2 * day, end_at=now - day)  # COMPLETED (vaqt bo‘yicha)
    AssignmentFactory(status=AssignmentStatus.COMPLETED)  # COMPLETED (qo‘lda)
    AssignmentFactory(status=AssignmentStatus.PAUSED)
    AssignmentFactory(status=AssignmentStatus.DRAFT)

    body = auth_client(admin).get(ADMIN).json()
    assert body["active_assignments"] == 1
    assert body["completed_assignments"] == 2


def test_admin_score_stats_use_latest_graded_attempt_per_student_and_assignment(auth_client, admin):
    a1, a2 = AssignmentFactory(), AssignmentFactory()
    s1, s2, s3 = StudentFactory.create_batch(3)
    graded(a1, s1, 1, 40, False)  # keyingisi bilan almashtirilgan
    graded(a1, s1, 2, 80, True)
    graded(a1, s2, 1, 60, True)
    graded(a2, s3, 1, 20, False)
    AttemptFactory(  # baholanmagan — hisobga olinmaydi
        assignment=a2, student=s1, attempt_number=1, status="PENDING_GRADING"
    )

    body = auth_client(admin).get(ADMIN).json()
    assert body["average_score"] == pytest.approx((80 + 60 + 20) / 3, abs=0.01)
    assert body["pass_rate"] == pytest.approx(66.67)


def test_admin_question_statistics(auth_client, admin):
    course = CourseFactory()
    module = ModuleFactory(course=course)
    author = TeacherFactory()
    single_used = QuestionFactory(course=course, module=module, created_by=author)
    QuestionFactory(course=course, module=module, created_by=author)
    multiple_used = QuestionFactory(
        course=course,
        module=module,
        created_by=author,
        type=QuestionType.MULTIPLE_CHOICE,
    )
    true_false = QuestionFactory(
        course=course, module=module, created_by=author, type=QuestionType.TRUE_FALSE
    )
    archived_question = QuestionFactory(
        course=course,
        module=module,
        created_by=author,
        type=QuestionType.OPEN_ENDED,
        status=QuestionStatus.ARCHIVED,
    )

    first_exam = ExamFactory(course=course, created_by=author)
    second_exam = ExamFactory(course=course, created_by=author)
    archived_exam = ExamFactory(course=course, created_by=author, status=ExamStatus.ARCHIVED)
    ExamQuestionFactory(exam=first_exam, question=single_used)
    ExamQuestionFactory(exam=second_exam, question=single_used)  # bir marta sanaladi
    ExamQuestionFactory(exam=first_exam, question=multiple_used)
    ExamQuestionFactory(exam=archived_exam, question=true_false)  # ishlatilgan hisoblanmaydi
    ExamQuestionFactory(exam=first_exam, question=archived_question)  # totalga kirmaydi

    statistics = auth_client(admin).get(ADMIN).json()["question_statistics"]

    assert statistics == {
        "total_questions": 4,
        "used_in_exams": 2,
        "used_in_exams_percentage": 50.0,
        "types": [
            {
                "type": "SINGLE_CHOICE",
                "label": "Single choice",
                "count": 2,
                "percentage": 50.0,
            },
            {
                "type": "MULTIPLE_CHOICE",
                "label": "Multiple choice",
                "count": 1,
                "percentage": 25.0,
            },
            {
                "type": "TRUE_FALSE",
                "label": "True / False",
                "count": 1,
                "percentage": 25.0,
            },
            {"type": "OPEN_ENDED", "label": "Open ended", "count": 0, "percentage": 0.0},
        ],
    }


def test_admin_course_overview(auth_client, admin):
    frontend = CourseFactory(name="Frontend development")
    backend = CourseFactory(name="Backend development")
    archived_course = CourseFactory(name="Archived", status=CourseStatus.ARCHIVED)

    active_student = StudentFactory()
    second_student = StudentFactory()
    inactive_student = StudentFactory(status=UserStatus.INACTIVE)
    EnrollmentFactory(course=frontend, student=active_student)
    EnrollmentFactory(course=frontend, student=second_student)
    EnrollmentFactory(course=frontend, student=inactive_student)
    EnrollmentFactory(course=frontend, status=EnrollmentStatus.REMOVED)
    EnrollmentFactory(course=backend)

    frontend_exam = ExamFactory(course=frontend)
    second_frontend_exam = ExamFactory(course=frontend, status=ExamStatus.READY)
    ExamFactory(course=frontend, status=ExamStatus.ARCHIVED)
    backend_exam = ExamFactory(course=backend)
    ExamFactory(course=archived_course)

    frontend_assignment = AssignmentFactory(exam=frontend_exam)
    graded(frontend_assignment, active_student, 1, 40, False)
    graded(frontend_assignment, active_student, 2, 80, True)
    graded(AssignmentFactory(exam=second_frontend_exam), second_student, 1, 60, True)
    graded(AssignmentFactory(exam=backend_exam), StudentFactory(), 1, 75, True)

    overview = auth_client(admin).get(ADMIN).json()["course_overview"]

    assert overview == [
        {
            "course_id": str(backend.id),
            "course_name": "Backend development",
            "students_count": 1,
            "exams_count": 1,
            "average_score": 75.0,
        },
        {
            "course_id": str(frontend.id),
            "course_name": "Frontend development",
            "students_count": 2,
            "exams_count": 2,
            "average_score": 70.0,
        },
    ]


def test_admin_dashboard_recent_activity_and_exam_statistics(auth_client, admin):
    student_a, student_b = StudentFactory.create_batch(2)
    assignment = AssignmentFactory()
    ExamAssignmentRecipient.objects.bulk_create(
        [
            ExamAssignmentRecipient(assignment=assignment, student=student_a),
            ExamAssignmentRecipient(assignment=assignment, student=student_b),
        ]
    )
    now = timezone.now()
    graded_attempt = graded(assignment, student_a, 1, 90, True)
    graded_attempt.deadline_at = now + timedelta(minutes=10)
    graded_attempt.submitted_at = now
    graded_attempt.save(update_fields=["deadline_at", "submitted_at"])
    AttemptFactory(
        assignment=assignment,
        student=student_b,
        status="PENDING_GRADING",
        submitted_at=now,
        deadline_at=now,
        finalization_reason=FinalizationReason.TIMEOUT,
    )
    AssignmentFactory(start_at=now + timedelta(days=3), end_at=None)

    body = auth_client(admin).get(ADMIN).json()

    assert body["summary"]["upcoming_assignments"]["next_7_days"] == 1
    assert body["recent_exams"][0]["id"]
    assert body["recent_results"][0]["attempt_id"] == str(graded_attempt.id)
    assert body["exam_activity"]["current_total"] == 2
    assert body["exam_statistics"] == {
        "completed_attempts": 2,
        "graded_attempts": 1,
        "passed_attempts": 1,
        "pass_rate": 100.0,
        "average_score": 90.0,
        "assigned_recipients": 2,
        "completed_recipients": 2,
        "completion_rate": 100.0,
        "tracked_submissions": 2,
        "on_time_submissions": 1,
        "on_time_submission_rate": 50.0,
    }
    assert {event["type"] for event in body["platform_activity"]} >= {
        "ASSIGNMENT_PUBLISHED",
        "EXAM_CREATED",
        "QUESTION_CREATED",
        "RESULT_RECORDED",
    }


# ------------------------------- teacher -------------------------------
def test_teacher_dashboard_numbers(auth_client, teacher):
    course_a, course_b = CourseFactory(), CourseFactory()
    archived = CourseFactory(status=CourseStatus.ARCHIVED)
    for course in (course_a, course_b, archived):
        CourseTeacherFactory(course=course, teacher=teacher)
    CourseTeacherFactory()  # boshqa teacher/kurs
    StudyGroupFactory(course=course_a)
    StudyGroupFactory(course=course_b)
    StudyGroupFactory(course=course_a, status=GroupStatus.ARCHIVED)
    StudyGroupFactory(course=archived)  # arxiv kurs guruhi sanalmaydi
    StudyGroupFactory()  # begona

    shared = StudentFactory()  # ikkala kursda ham o‘qiydi — bir marta sanaladi
    EnrollmentFactory(course=course_a, student=shared)
    EnrollmentFactory(course=course_b, student=shared)
    EnrollmentFactory(course=course_a)
    EnrollmentFactory(course=course_b, status=EnrollmentStatus.REMOVED)

    QuestionFactory(course=course_a, created_by=teacher)
    QuestionFactory(course=course_a, created_by=teacher, status=QuestionStatus.ARCHIVED)
    QuestionFactory(course=course_a)  # boshqa muallif
    ExamFactory(course=course_a, created_by=teacher)
    ExamFactory(course=course_a, created_by=teacher, status=ExamStatus.ARCHIVED)

    mine = AssignmentFactory(exam__course=course_a, published_by=teacher)  # ACTIVE
    AssignmentFactory(exam__course=course_a, published_by=teacher, status="DRAFT")
    colleagues = AssignmentFactory(exam__course=course_a)  # boshqa teacher e’loni

    graded(mine, shared, 1, 70, True)
    graded(colleagues, shared, 1, 30, False)
    AttemptFactory(
        assignment=colleagues, student=StudentFactory(), attempt_number=1, status="PENDING_GRADING"
    )
    graded(AssignmentFactory(), StudentFactory(), 1, 100, True)  # begona kurs

    body = auth_client(teacher).get(TEACHER).json()
    assert body == {
        "my_courses": 2,  # arxivlangan kurs sanalmaydi
        "my_groups": 2,
        "my_students": 2,  # `shared` ikkala kursda ham — bir marta; REMOVED sanalmaydi
        "my_questions": 1,  # faqat o‘zi yaratgan va ACTIVE
        "my_exams": 1,  # faqat o‘zi yaratgan va arxivlanmagan
        "active_assignments": 1,  # faqat o‘zi e’lon qilgan va hozir ACTIVE
        "pending_grading": 1,  # kurs bo‘yicha (hamkasbining e’loni ham)
        "average_student_score": 50.0,  # (70 + 30) / 2 — faqat o‘z kurslari
    }


# ------------------------------- student -------------------------------
def test_student_dashboard_numbers(auth_client, student):
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    EnrollmentFactory(student=student, status=EnrollmentStatus.COMPLETED)
    EnrollmentFactory(student=student, status=EnrollmentStatus.REMOVED)  # sanalmaydi

    open_one = AssignmentFactory(exam__course=course, max_attempts=2)  # mavjud
    resumable = AssignmentFactory(exam__course=course, max_attempts=1)  # davom ettirish mumkin
    AttemptFactory(assignment=resumable, student=student)  # IN_PROGRESS
    exhausted = AssignmentFactory(exam__course=course, max_attempts=1)  # limit tugagan
    graded(exhausted, student, 1, 40, False)
    AssignmentFactory(exam__course=course, start_at=timezone.now() + timedelta(days=1), end_at=None)
    AssignmentFactory(exam__course=course, status=AssignmentStatus.PAUSED)
    AssignmentFactory(exam__course=course, status=AssignmentStatus.DRAFT)
    AssignmentFactory()  # boshqa kurs

    done = AssignmentFactory(exam__course=course, max_attempts=None)
    graded(done, student, 1, 30, False)  # keyinroq yaxshilangan
    graded(done, student, 2, 90, True)
    pending = AssignmentFactory(exam__course=course, max_attempts=3)
    AttemptFactory(assignment=pending, student=student, attempt_number=1, status="PENDING_GRADING")

    body = auth_client(student).get(STUDENT).json()
    assert body["my_courses"] == 2
    # open_one, resumable, done (cheksiz), pending (limit qolgan); exhausted — yo‘q
    assert body["available_exams"] == 4
    assert body["completed_exams"] == 3  # exhausted, done, pending
    assert body["passed_exams"] == 1  # faqat `done` (oxirgi attempt bo‘yicha)
    assert body["average_score"] == pytest.approx((40 + 90) / 2)
    assert open_one.pk


def test_student_dashboard_closes_expired_attempts_first(auth_client, student):
    assignment = AssignmentFactory(max_attempts=1)
    EnrollmentFactory(course=assignment.exam.course, student=student)
    AttemptFactory(
        assignment=assignment,
        student=student,
        deadline_at=timezone.now() - timedelta(minutes=5),
    )
    body = auth_client(student).get(STUDENT).json()
    assert body["completed_exams"] == 1
    assert body["available_exams"] == 0  # limit tugagan


def test_dashboards_have_bounded_query_counts(
    auth_client, admin, teacher, student, django_assert_max_num_queries
):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    EnrollmentFactory(course=course, student=student)
    for number in range(1, 6):
        graded(AssignmentFactory(exam__course=course), student, number, 70, True)
    with django_assert_max_num_queries(35):
        assert auth_client(admin).get(ADMIN).status_code == 200
    with django_assert_max_num_queries(14):
        assert auth_client(teacher).get(TEACHER).status_code == 200
    with django_assert_max_num_queries(10):
        assert auth_client(student).get(STUDENT).status_code == 200

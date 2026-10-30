import pytest

from apps.academics.choices import CourseStatus, EnrollmentStatus
from apps.academics.tests.factories import CourseFactory, CourseTeacherFactory, EnrollmentFactory
from apps.assignments.tests.factories import AssignmentFactory
from apps.attempts.choices import AttemptStatus
from apps.attempts.tests.factories import AttemptFactory
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory
from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db


# --- /teachers, /students -----------------------------------------------
def test_teachers_and_students_endpoints_are_role_scoped(auth_client, admin):
    t = TeacherFactory()
    s = StudentFactory()
    client = auth_client(admin)

    teachers = client.get("/api/v1/teachers").json()["data"]
    students = client.get("/api/v1/students").json()["data"]
    assert [u["id"] for u in teachers] == [str(t.id)]
    assert [u["id"] for u in students] == [str(s.id)]

    # Teacher id si /students orqali topilmaydi.
    assert client.get(f"/api/v1/students/{t.id}").status_code == 404


def test_teachers_endpoint_forbidden_for_non_admin(auth_client, teacher):
    assert auth_client(teacher).get("/api/v1/teachers").status_code == 403


def test_teacher_directory_returns_courses_and_card_statistics(auth_client, admin):
    teacher = TeacherFactory(full_name="Nodira Ismoilova")
    active_course = CourseFactory(name="Frontend development")
    archived_course = CourseFactory(name="Old course", status=CourseStatus.ARCHIVED)
    CourseTeacherFactory(course=active_course, teacher=teacher)
    CourseTeacherFactory(course=archived_course, teacher=teacher)

    EnrollmentFactory.create_batch(2, course=active_course)
    EnrollmentFactory(course=active_course, status=EnrollmentStatus.REMOVED)
    EnrollmentFactory(course=archived_course)
    ExamFactory.create_batch(2, course=active_course, created_by=teacher)
    ExamFactory(course=active_course, created_by=teacher, status=ExamStatus.ARCHIVED)
    ExamFactory(course=archived_course, created_by=teacher)

    response = auth_client(admin).get("/api/v1/teachers", {"search": "nodira"})

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": str(teacher.id),
            "full_name": "Nodira Ismoilova",
            "email": teacher.email,
            "username": teacher.username,
            "role": "TEACHER",
            "avatar_url": "",
            "status": "ACTIVE",
            "created_at": response.json()["data"][0]["created_at"],
            "updated_at": response.json()["data"][0]["updated_at"],
            "assigned_courses": [
                {
                    "id": str(active_course.id),
                    "name": "Frontend development",
                    "teacher_type": "MAIN",
                }
            ],
            "courses_count": 1,
            "students_count": 2,
            "exams_count": 2,
        }
    ]


def test_teacher_directory_filters_by_course(auth_client, admin):
    selected_course = CourseFactory()
    matching = CourseTeacherFactory(course=selected_course).teacher
    CourseTeacherFactory()

    response = auth_client(admin).get("/api/v1/teachers", {"course_id": str(selected_course.id)})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [str(matching.id)]


def test_teacher_directory_summary(auth_client, admin):
    active = TeacherFactory()
    inactive = TeacherFactory(status=UserStatus.INACTIVE)
    first_course = CourseFactory()
    second_course = CourseFactory()
    CourseTeacherFactory(course=first_course, teacher=active)
    CourseTeacherFactory(course=first_course, teacher=inactive, type="SUPPORT")
    CourseTeacherFactory(course=second_course, teacher=active)
    EnrollmentFactory.create_batch(2, course=first_course)
    EnrollmentFactory(course=second_course)

    response = auth_client(admin).get("/api/v1/teachers/summary")

    assert response.status_code == 200
    assert response.json() == {
        "active_teachers": 1,
        "inactive_teachers": 1,
        "total_teachers": 2,
        "students_taught": 5,
        "course_assignments": 3,
    }


def test_teacher_directory_summary_forbidden_for_non_admin(auth_client, teacher):
    assert auth_client(teacher).get("/api/v1/teachers/summary").status_code == 403


def test_student_directory_returns_courses_and_latest_result_statistics(auth_client, admin):
    student = StudentFactory(full_name="Zarina Akhmedova")
    first_course = CourseFactory(name="UI development")
    second_course = CourseFactory(name="Frontend development")
    archived_course = CourseFactory(name="Old course", status=CourseStatus.ARCHIVED)
    first_enrollment = EnrollmentFactory(course=first_course, student=student)
    EnrollmentFactory(course=second_course, student=student)
    EnrollmentFactory(course=archived_course, student=student)

    first_assignment = AssignmentFactory(exam__course=first_course)
    second_assignment = AssignmentFactory(exam__course=second_course)
    AttemptFactory(
        assignment=first_assignment,
        student=student,
        attempt_number=1,
        status=AttemptStatus.GRADED,
        percentage=60,
        passed=False,
    )
    AttemptFactory(
        assignment=first_assignment,
        student=student,
        attempt_number=2,
        status=AttemptStatus.GRADED,
        percentage=90,
        passed=True,
    )
    AttemptFactory(
        assignment=second_assignment,
        student=student,
        status=AttemptStatus.GRADED,
        percentage=50,
        passed=False,
    )
    AttemptFactory(student=student)  # IN_PROGRESS natijaga kirmaydi.

    response = auth_client(admin).get("/api/v1/students", {"search": "zarina"})

    assert response.status_code == 200
    body = response.json()["data"][0]
    assert body["id"] == str(student.id)
    assert body["enrolled_courses"] == [
        {
            "enrollment_id": str(first_enrollment.id),
            "course_id": str(first_course.id),
            "course_name": "UI development",
            "status": "ACTIVE",
        },
        {
            "enrollment_id": body["enrolled_courses"][1]["enrollment_id"],
            "course_id": str(second_course.id),
            "course_name": "Frontend development",
            "status": "ACTIVE",
        },
    ]
    assert body["courses_count"] == 2
    assert body["exams_taken"] == 2
    assert body["average_score"] == 70.0
    assert body["passed_exams"] == 1


def test_student_directory_filters_by_course_status_and_first_letter(auth_client, admin):
    course = CourseFactory()
    matching = EnrollmentFactory(
        course=course,
        student=StudentFactory(full_name="Zarina Akhmedova"),
    ).student
    EnrollmentFactory(
        course=course,
        student=StudentFactory(full_name="Zafar Inactive", status=UserStatus.INACTIVE),
    )
    EnrollmentFactory(
        course=course,
        student=StudentFactory(full_name="Ziyoda Removed"),
        status=EnrollmentStatus.REMOVED,
    )
    StudentFactory(full_name="Ali Other")

    response = auth_client(admin).get(
        "/api/v1/students",
        {
            "course_id": str(course.id),
            "status": "ACTIVE",
            "first_letter": "z",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [str(matching.id)]


def test_student_directory_summary_uses_latest_graded_attempts(auth_client, admin):
    active = StudentFactory()
    inactive = StudentFactory(status=UserStatus.INACTIVE)
    course = CourseFactory()
    EnrollmentFactory(course=course, student=active)
    EnrollmentFactory(course=course, student=inactive)
    EnrollmentFactory(course=course, status=EnrollmentStatus.REMOVED)
    assignment = AssignmentFactory(exam__course=course)
    AttemptFactory(
        assignment=assignment,
        student=active,
        attempt_number=1,
        status=AttemptStatus.GRADED,
        percentage=40,
        passed=False,
    )
    AttemptFactory(
        assignment=assignment,
        student=active,
        attempt_number=2,
        status=AttemptStatus.GRADED,
        percentage=80,
        passed=True,
    )
    other_assignment = AssignmentFactory(exam__course=course)
    AttemptFactory(
        assignment=other_assignment,
        student=inactive,
        status=AttemptStatus.GRADED,
        percentage=60,
        passed=False,
    )

    response = auth_client(admin).get("/api/v1/students/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_students": 3,
        "active_students": 2,
        "inactive_students": 1,
        "course_enrollments": 2,
        "average_score": 70.0,
        "passed_exams": 1,
    }


def test_student_directory_summary_forbidden_for_non_admin(auth_client, student):
    assert auth_client(student).get("/api/v1/students/summary").status_code == 403

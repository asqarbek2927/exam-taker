import pytest
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.academics.choices import CourseStatus, EnrollmentStatus
from apps.academics.tests.factories import CourseFactory, CourseTeacherFactory, EnrollmentFactory
from apps.assignments.tests.factories import AssignmentFactory
from apps.attempts.choices import AttemptStatus
from apps.attempts.tests.factories import AttemptFactory
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory
from apps.users import services
from apps.users.choices import UserRole, UserStatus
from apps.users.models import User
from apps.users.tests.factories import (
    DEFAULT_PASSWORD,
    StudentFactory,
    TeacherFactory,
)

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users"


def payload(**overrides):
    data = {
        "full_name": "Yangi Teacher",
        "email": "New.Teacher@Example.com",
        "password": DEFAULT_PASSWORD,
        "role": "TEACHER",
    }
    data.update(overrides)
    return data


# --- permissions ---------------------------------------------------------
@pytest.mark.parametrize("role_fixture", ["teacher", "student"])
def test_non_admin_cannot_access_users(request, auth_client, role_fixture):
    client = auth_client(request.getfixturevalue(role_fixture))
    assert client.get(USERS).status_code == 403
    assert client.post(USERS, payload(), format="json").status_code == 403


def test_anonymous_gets_401(api_client):
    assert api_client.get(USERS).status_code == 401


# --- create --------------------------------------------------------------
def test_admin_creates_teacher(auth_client, admin):
    response = auth_client(admin).post(USERS, payload(), format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.teacher@example.com"
    assert body["role"] == "TEACHER"
    assert body["status"] == "ACTIVE"
    assert body["avatar_url"] == ""
    assert "password" not in body
    assert body["generated_password"] is None
    assert User.objects.get(pk=body["id"]).check_password(DEFAULT_PASSWORD)


def test_admin_creates_student(auth_client, admin):
    response = auth_client(admin).post(
        USERS, payload(role="STUDENT", email="s@example.com"), format="json"
    )
    assert response.status_code == 201
    assert response.json()["role"] == "STUDENT"


def test_admin_can_create_user_with_generated_password(api_client, auth_client, admin):
    data = payload(
        role="STUDENT",
        email="generated@example.com",
        avatar_url=None,
        generate_random_password=True,
    )
    del data["password"]

    response = auth_client(admin).post(USERS, data, format="json")
    assert response.status_code == 201
    generated_password = response.json()["generated_password"]
    assert isinstance(generated_password, str)
    assert len(generated_password) == services.PASSWORD_LENGTH

    user = User.objects.get(email="generated@example.com")
    assert user.avatar_url == ""
    assert user.check_password(generated_password)
    assert auth_client(admin).get(f"{USERS}/{user.id}").json().get("generated_password") is None
    login = api_client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": generated_password},
        format="json",
    )
    assert login.status_code == 200


@pytest.mark.parametrize("password", ["", None])
def test_create_rejects_blank_or_null_password_when_field_is_sent(auth_client, admin, password):
    response = auth_client(admin).post(USERS, payload(password=password), format="json")
    assert response.status_code == 422
    assert "password" in response.json()["errors"]


def test_create_validates_random_password_mode(auth_client, admin):
    response = auth_client(admin).post(
        USERS,
        payload(generate_random_password=True, password=DEFAULT_PASSWORD),
        format="json",
    )
    assert response.status_code == 422
    assert "password" in response.json()["errors"]

    without_password = payload(generate_random_password=False)
    del without_password["password"]
    response = auth_client(admin).post(USERS, without_password, format="json")
    assert response.status_code == 422
    assert "password" in response.json()["errors"]


def test_cannot_create_super_admin_via_api(auth_client, admin):
    response = auth_client(admin).post(USERS, payload(role="SUPER_ADMIN"), format="json")
    assert response.status_code == 422
    assert "role" in response.json()["errors"]


def test_duplicate_email_is_rejected_case_insensitively(auth_client, admin, teacher):
    response = auth_client(admin).post(USERS, payload(email=teacher.email.upper()), format="json")
    assert response.status_code == 422
    assert "email" in response.json()["errors"]


def test_weak_password_is_rejected(auth_client, admin):
    response = auth_client(admin).post(USERS, payload(password="12345678"), format="json")
    assert response.status_code == 422
    assert (
        "non_field_errors" in response.json()["errors"] or "password" in response.json()["errors"]
    )
    assert not User.objects.filter(email="new.teacher@example.com").exists()


# --- list / filters / pagination ----------------------------------------
def test_list_uses_pagination_contract(auth_client, admin):
    TeacherFactory.create_batch(3)
    response = auth_client(admin).get(USERS, {"limit": 2, "page": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"] == {"page": 1, "limit": 2, "total": 4, "total_pages": 2}


def test_list_filters_by_role_status_and_search(auth_client, admin):
    TeacherFactory(full_name="Zoir Karimov")
    StudentFactory(full_name="Dilnoza Aliyeva")
    StudentFactory(full_name="Inactive One", status=UserStatus.INACTIVE)
    client = auth_client(admin)

    students = client.get(USERS, {"role": "STUDENT"}).json()["data"]
    assert {u["role"] for u in students} == {"STUDENT"}
    assert len(students) == 2

    inactive = client.get(USERS, {"status": "INACTIVE"}).json()["data"]
    assert [u["full_name"] for u in inactive] == ["Inactive One"]

    found = client.get(USERS, {"search": "zoir"}).json()["data"]
    assert [u["full_name"] for u in found] == ["Zoir Karimov"]


def test_invalid_filter_value_returns_422(auth_client, admin):
    response = auth_client(admin).get(USERS, {"role": "BOSS"})
    assert response.status_code == 422


def test_non_uuid_id_returns_404_in_error_format(auth_client, admin):
    response = auth_client(admin).get(f"{USERS}/not-a-uuid")
    assert response.status_code == 404
    assert response.json() == {
        "status_code": 404,
        "error": "Not Found",
        "message": "Resurs topilmadi.",
    }


# --- retrieve / update ---------------------------------------------------
def test_retrieve_and_update(auth_client, admin, teacher):
    client = auth_client(admin)
    assert client.get(f"{USERS}/{teacher.id}").json()["email"] == teacher.email

    response = client.patch(
        f"{USERS}/{teacher.id}",
        {"full_name": "Yangi Ism", "email": "CHANGED@example.com"},
        format="json",
    )
    assert response.status_code == 200
    teacher.refresh_from_db()
    assert teacher.full_name == "Yangi Ism"
    assert teacher.email == "changed@example.com"


def test_update_cannot_change_role_or_status(auth_client, admin, teacher):
    auth_client(admin).patch(
        f"{USERS}/{teacher.id}", {"role": "SUPER_ADMIN", "status": "INACTIVE"}, format="json"
    )
    teacher.refresh_from_db()
    assert teacher.role == UserRole.TEACHER
    assert teacher.status == UserStatus.ACTIVE


def test_update_email_conflict_returns_422(auth_client, admin, teacher):
    other = TeacherFactory()
    response = auth_client(admin).patch(
        f"{USERS}/{teacher.id}", {"email": other.email}, format="json"
    )
    assert response.status_code == 422


def test_delete_is_not_allowed(auth_client, admin, teacher):
    assert auth_client(admin).delete(f"{USERS}/{teacher.id}").status_code == 405


# --- activate / deactivate / set-password -------------------------------
def test_deactivate_and_activate(auth_client, admin, teacher):
    client = auth_client(admin)
    response = client.post(f"{USERS}/{teacher.id}/deactivate")
    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"

    response = client.post(f"{USERS}/{teacher.id}/activate")
    assert response.json()["status"] == "ACTIVE"


def test_admin_cannot_deactivate_self(auth_client, admin):
    response = auth_client(admin).post(f"{USERS}/{admin.id}/deactivate")
    assert response.status_code == 400
    admin.refresh_from_db()
    assert admin.is_active


def test_deactivate_revokes_refresh_tokens(api_client, auth_client, admin, teacher):
    login = api_client.post(
        "/api/v1/auth/login",
        {"email": teacher.email, "password": DEFAULT_PASSWORD},
        format="json",
    ).json()
    assert OutstandingToken.objects.filter(user=teacher).count() == 1

    auth_client(admin).post(f"{USERS}/{teacher.id}/deactivate")
    assert BlacklistedToken.objects.filter(token__user=teacher).count() == 1

    refresh = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": login["refresh_token"]}, format="json"
    )
    assert refresh.status_code == 401


def test_set_password(api_client, auth_client, admin, teacher):
    new_password = "An0ther-Str0ng-Pass!"
    response = auth_client(admin).post(
        f"{USERS}/{teacher.id}/set-password", {"password": new_password}, format="json"
    )
    assert response.status_code == 204

    ok = api_client.post(
        "/api/v1/auth/login", {"email": teacher.email, "password": new_password}, format="json"
    )
    assert ok.status_code == 200
    old = api_client.post(
        "/api/v1/auth/login",
        {"email": teacher.email, "password": DEFAULT_PASSWORD},
        format="json",
    )
    assert old.status_code == 401


def test_set_password_rejects_weak_password(auth_client, admin, teacher):
    response = auth_client(admin).post(
        f"{USERS}/{teacher.id}/set-password", {"password": "short"}, format="json"
    )
    assert response.status_code == 422


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

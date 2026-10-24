import pytest

from apps.academics.choices import CourseStatus, CourseTeacherType, EnrollmentStatus
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
)
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

COURSES = "/api/v1/courses"


def test_admin_creates_and_updates_course(auth_client, admin):
    client = auth_client(admin)
    response = client.post(COURSES, {"name": "Django", "description": "Backend"}, format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Django"
    assert body["status"] == "ACTIVE"
    assert body["teachers_count"] == 0
    assert body["students_count"] == 0
    assert body["main_teacher"] is None
    assert body["support_teachers"] == []

    updated = client.patch(f"{COURSES}/{body['id']}", {"name": "Django 5"}, format="json")
    assert updated.status_code == 200
    assert updated.json()["name"] == "Django 5"
    assert updated.json()["description"] == "Backend"


def test_create_course_validation(auth_client, admin):
    response = auth_client(admin).post(COURSES, {"description": "x"}, format="json")
    assert response.status_code == 422
    assert "name" in response.json()["errors"]


@pytest.mark.parametrize("role_fixture", ["teacher", "student"])
def test_non_admin_cannot_write_courses(request, auth_client, role_fixture):
    client = auth_client(request.getfixturevalue(role_fixture))
    course = CourseFactory()
    assert client.post(COURSES, {"name": "X"}, format="json").status_code == 403
    assert client.patch(f"{COURSES}/{course.id}", {"name": "Y"}, format="json").status_code == 403
    assert client.post(f"{COURSES}/{course.id}/archive").status_code == 403


def test_anonymous_cannot_list_courses(api_client):
    assert api_client.get(COURSES).status_code == 401


def test_admin_sees_all_courses(auth_client, admin):
    CourseFactory.create_batch(3)
    body = auth_client(admin).get(COURSES).json()
    assert body["pagination"]["total"] == 3


def test_teacher_sees_only_assigned_courses(auth_client, teacher):
    mine = CourseFactory()
    CourseFactory()  # boshqa kurs
    CourseTeacherFactory(course=mine, teacher=teacher, type=CourseTeacherType.SUPPORT)
    client = auth_client(teacher)

    data = client.get(COURSES).json()["data"]
    assert [c["id"] for c in data] == [str(mine.id)]
    assert client.get(f"{COURSES}/{mine.id}").status_code == 200


def test_teacher_gets_404_for_unassigned_course(auth_client, teacher):
    other = CourseFactory()
    assert auth_client(teacher).get(f"{COURSES}/{other.id}").status_code == 404


def test_student_sees_only_enrolled_courses(auth_client, student):
    mine = CourseFactory()
    removed = CourseFactory()
    CourseFactory()
    EnrollmentFactory(course=mine, student=student)
    EnrollmentFactory(course=removed, student=student, status=EnrollmentStatus.REMOVED)
    client = auth_client(student)

    data = client.get(COURSES).json()["data"]
    assert [c["id"] for c in data] == [str(mine.id)]
    assert client.get(f"{COURSES}/{removed.id}").status_code == 404


def test_counts_are_not_distorted_by_role_scoping(auth_client, teacher, student):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher, type=CourseTeacherType.MAIN)
    CourseTeacherFactory(course=course, type=CourseTeacherType.SUPPORT)
    EnrollmentFactory(course=course, student=student)
    EnrollmentFactory(course=course)
    EnrollmentFactory(course=course, status=EnrollmentStatus.REMOVED)

    for user in (teacher, student):
        body = auth_client(user).get(f"{COURSES}/{course.id}").json()
        assert body["teachers_count"] == 2
        assert body["students_count"] == 2


def test_course_detail_has_main_and_support_teachers(auth_client, admin):
    course = CourseFactory()
    main = CourseTeacherFactory(course=course, type=CourseTeacherType.MAIN).teacher
    support = CourseTeacherFactory(course=course, type=CourseTeacherType.SUPPORT).teacher

    body = auth_client(admin).get(f"{COURSES}/{course.id}").json()
    assert body["main_teacher"]["id"] == str(main.id)
    assert [t["id"] for t in body["support_teachers"]] == [str(support.id)]


def test_course_list_filter_and_search(auth_client, admin):
    CourseFactory(name="Python Foundation")
    CourseFactory(name="Django Backend", status=CourseStatus.ARCHIVED)
    client = auth_client(admin)

    archived = client.get(COURSES, {"status": "ARCHIVED"}).json()["data"]
    assert [c["name"] for c in archived] == ["Django Backend"]
    found = client.get(COURSES, {"search": "python"}).json()["data"]
    assert [c["name"] for c in found] == ["Python Foundation"]


def test_archive_course_makes_it_read_only(auth_client, admin):
    course = CourseFactory()
    client = auth_client(admin)

    response = client.post(f"{COURSES}/{course.id}/archive")
    assert response.status_code == 200
    assert response.json()["status"] == "ARCHIVED"

    update = client.patch(f"{COURSES}/{course.id}", {"name": "New"}, format="json")
    assert update.status_code == 400
    assert update.json()["message"] == "Arxivlangan kursga o‘zgartirish kiritib bo‘lmaydi."

    teacher = TeacherFactory()
    assign = client.post(
        f"{COURSES}/{course.id}/teachers",
        {"teacher_id": str(teacher.id), "type": "MAIN"},
        format="json",
    )
    assert assign.status_code == 400

    student = StudentFactory()
    enroll = client.post(
        f"{COURSES}/{course.id}/students", {"student_id": str(student.id)}, format="json"
    )
    assert enroll.status_code == 400


def test_archive_is_idempotent(auth_client, admin):
    course = CourseFactory(status=CourseStatus.ARCHIVED)
    assert auth_client(admin).post(f"{COURSES}/{course.id}/archive").status_code == 200

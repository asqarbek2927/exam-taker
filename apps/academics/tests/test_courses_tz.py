import pytest

from apps.academics.choices import CourseTeacherType, EnrollmentStatus, ModuleStatus
from apps.academics.models import Enrollment
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    ModuleFactory,
)
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db


def test_course_tz_create_filter_detail_and_optimistic_update(auth_client, admin):
    main = TeacherFactory(full_name="Main Teacher")
    support = TeacherFactory(full_name="Support Teacher")
    client = auth_client(admin)

    created = client.post(
        "/api/v1/courses",
        {
            "name": "Python Advanced",
            "description": "TZ course",
            "mainTeacherId": str(main.id),
            "teacherIds": [str(main.id), str(support.id)],
            "status": "DRAFT",
        },
        format="json",
    )

    assert created.status_code == 201
    body = created.json()
    assert body["version"] == 1
    assert body["main_teacher"]["id"] == str(main.id)
    assert len(body["support_teachers"]) == 1
    assert body["actions"]["can_edit"] is True

    found = client.get("/api/v1/courses", {"q": "advanced", "teacherId": str(support.id)}).json()[
        "data"
    ]
    assert [item["id"] for item in found] == [body["id"]]

    updated = client.patch(
        f"/api/v1/courses/{body['id']}",
        {"description": "Updated", "version": 1},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    stale = client.patch(
        f"/api/v1/courses/{body['id']}",
        {"description": "Stale", "version": 1},
        format="json",
    )
    assert stale.status_code == 409


def test_course_and_module_status_and_exact_order(auth_client, admin):
    course = CourseFactory(status="ACTIVE")
    first = ModuleFactory(course=course, position=8)
    second = ModuleFactory(course=course, position=2)
    client = auth_client(admin)
    base = f"/api/v1/courses/{course.id}/modules"

    reordered = client.put(
        f"{base}/order",
        {"moduleIds": [str(first.id), str(second.id)]},
        format="json",
    )
    assert reordered.status_code == 200
    assert [(item["id"], item["position"]) for item in reordered.json()] == [
        (str(first.id), 1),
        (str(second.id), 2),
    ]

    invalid = client.put(f"{base}/order", {"moduleIds": [str(first.id)]}, format="json")
    assert invalid.status_code == 400

    archived = client.put(f"{base}/{first.id}/status", {"status": "ARCHIVED"}, format="json")
    assert archived.status_code == 200
    assert archived.json()["status"] == ModuleStatus.ARCHIVED

    course_status = client.put(
        f"/api/v1/courses/{course.id}/status",
        {"status": "ARCHIVED", "version": 1},
        format="json",
    )
    assert course_status.status_code == 200
    assert course_status.json()["status"] == "ARCHIVED"
    assert course_status.json()["version"] == 2


def test_enrollment_tz_alias_is_idempotent_and_deletes_by_student_id(auth_client, admin, student):
    course = CourseFactory(status="ACTIVE")
    client = auth_client(admin)
    base = f"/api/v1/courses/{course.id}/enrollments"

    first = client.post(base, {"studentId": str(student.id)}, format="json")
    second = client.post(base, {"studentId": str(student.id)}, format="json")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    removed = client.delete(f"{base}/{student.id}")
    assert removed.status_code == 204
    assert Enrollment.objects.get(course=course, student=student).status == EnrollmentStatus.REMOVED


def test_enrollment_alias_requires_active_course(auth_client, admin):
    course = CourseFactory(status="DRAFT")
    student = StudentFactory()
    response = auth_client(admin).post(
        f"/api/v1/courses/{course.id}/enrollments",
        {"studentId": str(student.id)},
        format="json",
    )
    assert response.status_code == 400


def test_student_my_courses_is_scoped(auth_client, student):
    mine = CourseFactory(name="Mine")
    other = CourseFactory(name="Other")
    teacher = TeacherFactory(full_name="Course Teacher")
    CourseTeacherFactory(course=mine, teacher=teacher, type=CourseTeacherType.MAIN)
    EnrollmentFactory(course=mine, student=student)
    EnrollmentFactory(course=other, status=EnrollmentStatus.ACTIVE)
    ModuleFactory.create_batch(2, course=mine)

    response = auth_client(student).get("/api/v1/students/me/courses")

    assert response.status_code == 200
    assert len(response.json()) == 1
    card = response.json()[0]
    assert card["course_id"] == str(mine.id)
    assert card["title"] == "Mine"
    assert card["teacher_names"] == ["Course Teacher"]
    assert card["module_count"] == 2
    assert card["progress"] is None
    assert card["next_step"] == "VIEW_AVAILABLE_EXAMS"


def test_non_student_cannot_use_student_course_cards(auth_client, teacher):
    assert auth_client(teacher).get("/api/v1/students/me/courses").status_code == 403

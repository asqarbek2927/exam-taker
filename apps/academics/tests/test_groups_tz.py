import pytest

from apps.academics.choices import GroupStatus
from apps.academics.models import GroupStudent
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    GroupStudentFactory,
    StudyGroupFactory,
)
from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db

GROUPS = "/api/v1/groups"


def test_group_tz_create_filter_update_and_version(auth_client, admin):
    course = CourseFactory(name="Python Backend")
    main = CourseTeacherFactory(course=course).teacher
    support = CourseTeacherFactory(course=course, type="SUPPORT").teacher
    client = auth_client(admin)

    created = client.post(
        GROUPS,
        {
            "name": "Backend A",
            "courseId": str(course.id),
            "mainTeacherId": str(main.id),
            "supportTeacherId": str(support.id),
            "status": "ACTIVE",
        },
        format="json",
    )

    assert created.status_code == 201
    body = created.json()
    assert body["version"] == 1
    assert body["main_teacher"]["id"] == str(main.id)

    found = client.get(
        GROUPS, {"courseId": str(course.id), "status": "ACTIVE", "q": "backend"}
    ).json()["data"]
    assert [item["id"] for item in found] == [body["id"]]

    updated = client.patch(
        f"{GROUPS}/{body['id']}",
        {"name": "Backend B", "version": 1},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    stale = client.patch(
        f"{GROUPS}/{body['id']}",
        {"name": "Stale", "version": 1},
        format="json",
    )
    assert stale.status_code == 409
    assert client.put(f"{GROUPS}/{body['id']}", {"name": "No"}, format="json").status_code == 405


def test_group_directory_and_detail_are_role_scoped(auth_client, teacher, student):
    mine = CourseFactory()
    other = CourseFactory()
    CourseTeacherFactory(course=mine, teacher=teacher)
    teacher_group = StudyGroupFactory(course=mine)
    StudyGroupFactory(course=other)
    student_group = StudyGroupFactory(course=other)
    GroupStudentFactory(group=student_group, student=student)
    classmate = GroupStudentFactory(group=student_group).student

    teacher_data = auth_client(teacher).get(GROUPS).json()["data"]
    assert [item["id"] for item in teacher_data] == [str(teacher_group.id)]

    student_client = auth_client(student)
    student_data = student_client.get(GROUPS).json()["data"]
    assert [item["id"] for item in student_data] == [str(student_group.id)]
    assert student_data[0]["students_preview"][0]["id"] == str(student.id)

    detail = student_client.get(f"{GROUPS}/{student_group.id}")
    assert detail.status_code == 200
    assert detail.json()["students"] == []
    assert student_client.get(f"{GROUPS}/{teacher_group.id}").status_code == 404
    assert str(classmate.id) not in str(detail.json())


def test_staff_group_detail_contains_full_roster(auth_client, admin):
    group = StudyGroupFactory()
    students = [GroupStudentFactory(group=group).student for _ in range(2)]

    detail = auth_client(admin).get(f"{GROUPS}/{group.id}").json()

    assert {item["id"] for item in detail["students"]} == {str(student.id) for student in students}


def test_group_status_restore_checks_one_active_group_rule(auth_client, admin):
    course = CourseFactory()
    archived = StudyGroupFactory(course=course, status=GroupStatus.ARCHIVED)
    active = StudyGroupFactory(course=course)
    student = StudentFactory()
    GroupStudentFactory(group=archived, student=student)
    GroupStudentFactory(group=active, student=student)
    client = auth_client(admin)

    conflict = client.put(
        f"{GROUPS}/{archived.id}/status",
        {"status": "ACTIVE", "version": 1},
        format="json",
    )
    assert conflict.status_code == 409

    GroupStudent.objects.filter(group=active, student=student).delete()
    restored = client.put(
        f"{GROUPS}/{archived.id}/status",
        {"status": "ACTIVE", "version": 1},
        format="json",
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "ACTIVE"
    assert restored.json()["version"] == 2


def test_eligible_students_are_active_enrolled_and_ungrouped(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    other_group = StudyGroupFactory(course=course)
    eligible = EnrollmentFactory(course=course, student=StudentFactory(full_name="Eligible One"))
    grouped = EnrollmentFactory(course=course, student=StudentFactory(full_name="Grouped One"))
    inactive = EnrollmentFactory(
        course=course,
        student=StudentFactory(full_name="Inactive One", status=UserStatus.INACTIVE),
    )
    GroupStudentFactory(group=other_group, student=grouped.student)
    StudentFactory(full_name="Not Enrolled")

    response = auth_client(admin).get(f"{GROUPS}/{group.id}/eligible-students", {"q": "eligible"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [str(eligible.student_id)]
    ids = {
        item["id"]
        for item in auth_client(admin).get(f"{GROUPS}/{group.id}/eligible-students").json()["data"]
    }
    assert str(grouped.student_id) not in ids
    assert str(inactive.student_id) not in ids


def test_global_group_membership_endpoints_and_single_active_group(auth_client, admin):
    course = CourseFactory(status="ACTIVE")
    first = StudyGroupFactory(course=course)
    second = StudyGroupFactory(course=course)
    enrollment = EnrollmentFactory(course=course)
    student = enrollment.student
    client = auth_client(admin)

    created = client.post(
        f"{GROUPS}/{first.id}/students",
        {"studentId": str(student.id)},
        format="json",
    )
    assert created.status_code == 201

    duplicate_course_group = client.post(
        f"{GROUPS}/{second.id}/students",
        {"studentId": str(student.id)},
        format="json",
    )
    assert duplicate_course_group.status_code == 409

    removed = client.delete(f"{GROUPS}/{first.id}/students/{student.id}")
    assert removed.status_code == 204
    assert not GroupStudent.objects.filter(group=first, student=student).exists()

    moved = client.post(
        f"{GROUPS}/{second.id}/students",
        {"studentId": str(student.id)},
        format="json",
    )
    assert moved.status_code == 201


def test_group_membership_requires_active_group_course_and_admin(auth_client, admin, teacher):
    course = CourseFactory(status="ACTIVE")
    archived = StudyGroupFactory(course=course, status="ARCHIVED")
    enrollment = EnrollmentFactory(course=course)
    body = {"studentId": str(enrollment.student_id)}

    assert (
        auth_client(admin).post(f"{GROUPS}/{archived.id}/students", body, format="json").status_code
        == 400
    )
    assert (
        auth_client(teacher)
        .post(f"{GROUPS}/{archived.id}/students", body, format="json")
        .status_code
        == 403
    )

    historical = GroupStudentFactory(group=archived, student=enrollment.student)
    removed = auth_client(admin).delete(f"{GROUPS}/{archived.id}/students/{enrollment.student_id}")
    assert removed.status_code == 204
    assert not GroupStudent.objects.filter(pk=historical.pk).exists()

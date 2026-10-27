import pytest
from django.db import IntegrityError, transaction

from apps.academics.choices import CourseTeacherType, EnrollmentStatus
from apps.academics.models import CourseTeacher, Enrollment
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    StudyGroupFactory,
)
from apps.users.choices import UserStatus
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db


def teachers_url(course):
    return f"/api/v1/courses/{course.id}/teachers"


def students_url(course):
    return f"/api/v1/courses/{course.id}/students"


# ======================= teachers =======================
def test_admin_assigns_teacher(auth_client, admin):
    course = CourseFactory()
    teacher = TeacherFactory()
    response = auth_client(admin).post(
        teachers_url(course), {"teacher_id": str(teacher.id), "type": "MAIN"}, format="json"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "MAIN"
    assert body["teacher"]["id"] == str(teacher.id)
    assert CourseTeacher.objects.filter(course=course, teacher=teacher).exists()


def test_assign_same_teacher_twice_returns_409(auth_client, admin):
    ct = CourseTeacherFactory()
    response = auth_client(admin).post(
        teachers_url(ct.course),
        {"teacher_id": str(ct.teacher_id), "type": "SUPPORT"},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["status_code"] == 409


def test_cannot_assign_second_main_teacher(auth_client, admin):
    existing = CourseTeacherFactory(type=CourseTeacherType.MAIN)
    teacher = TeacherFactory()

    response = auth_client(admin).post(
        teachers_url(existing.course),
        {"teacher_id": str(teacher.id), "type": "MAIN"},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["message"] == "Bu kursga MAIN teacher allaqachon biriktirilgan."
    assert (
        CourseTeacher.objects.filter(course=existing.course, type=CourseTeacherType.MAIN).count()
        == 1
    )


def test_database_rejects_second_main_teacher():
    existing = CourseTeacherFactory(type=CourseTeacherType.MAIN)

    with pytest.raises(IntegrityError), transaction.atomic():
        CourseTeacherFactory(course=existing.course, type=CourseTeacherType.MAIN)


def test_cannot_assign_non_teacher(auth_client, admin, student):
    course = CourseFactory()
    response = auth_client(admin).post(
        teachers_url(course), {"teacher_id": str(student.id), "type": "MAIN"}, format="json"
    )
    # STUDENT queryset da yo‘q -> validation xatosi
    assert response.status_code == 422
    assert "teacher_id" in response.json()["errors"]


def test_cannot_assign_inactive_teacher(auth_client, admin):
    course = CourseFactory()
    teacher = TeacherFactory(status=UserStatus.INACTIVE)
    response = auth_client(admin).post(
        teachers_url(course), {"teacher_id": str(teacher.id), "type": "MAIN"}, format="json"
    )
    assert response.status_code == 400


def test_assign_teacher_validation(auth_client, admin):
    course = CourseFactory()
    response = auth_client(admin).post(
        teachers_url(course), {"teacher_id": "not-a-uuid", "type": "BOSS"}, format="json"
    )
    assert response.status_code == 422
    assert set(response.json()["errors"]) == {"teacher_id", "type"}


def test_change_teacher_type_and_remove(auth_client, admin):
    ct = CourseTeacherFactory(type=CourseTeacherType.MAIN)
    client = auth_client(admin)
    url = f"{teachers_url(ct.course)}/{ct.id}"

    response = client.patch(url, {"type": "SUPPORT"}, format="json")
    assert response.status_code == 200
    assert response.json()["type"] == "SUPPORT"

    assert client.delete(url).status_code == 204
    assert not CourseTeacher.objects.filter(pk=ct.pk).exists()


def test_cannot_remove_teacher_used_by_group(auth_client, admin):
    course = CourseFactory()
    assignment = CourseTeacherFactory(course=course)
    StudyGroupFactory(course=course, main_teacher=assignment.teacher)

    response = auth_client(admin).delete(f"{teachers_url(course)}/{assignment.id}")

    assert response.status_code == 409
    assert CourseTeacher.objects.filter(pk=assignment.pk).exists()


def test_cannot_change_second_teacher_to_main(auth_client, admin):
    course = CourseFactory()
    CourseTeacherFactory(course=course, type=CourseTeacherType.MAIN)
    support = CourseTeacherFactory(course=course, type=CourseTeacherType.SUPPORT)

    response = auth_client(admin).patch(
        f"{teachers_url(course)}/{support.id}", {"type": "MAIN"}, format="json"
    )

    assert response.status_code == 409
    support.refresh_from_db()
    assert support.type == CourseTeacherType.SUPPORT


def test_teacher_cannot_touch_another_courses_assignment(auth_client, admin):
    ct = CourseTeacherFactory()
    other_course = CourseFactory()
    response = auth_client(admin).delete(f"{teachers_url(other_course)}/{ct.id}")
    assert response.status_code == 404


def test_assigned_teacher_can_list_teachers_but_not_modify(auth_client, teacher):
    course = CourseFactory()
    ct = CourseTeacherFactory(course=course, teacher=teacher, type=CourseTeacherType.SUPPORT)
    CourseTeacherFactory(course=course, type=CourseTeacherType.MAIN)
    client = auth_client(teacher)

    listing = client.get(teachers_url(course))
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total"] == 2
    # MAIN birinchi
    assert listing.json()["data"][0]["type"] == "MAIN"

    assert client.delete(f"{teachers_url(course)}/{ct.id}").status_code == 403
    other = TeacherFactory()
    assert (
        client.post(
            teachers_url(course), {"teacher_id": str(other.id), "type": "MAIN"}, format="json"
        ).status_code
        == 403
    )


def test_unassigned_teacher_gets_404_on_course_teachers(auth_client, teacher):
    assert auth_client(teacher).get(teachers_url(CourseFactory())).status_code == 404


def test_student_cannot_list_course_teachers(auth_client, student):
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    assert auth_client(student).get(teachers_url(course)).status_code == 403


# ======================= students (enrollments) =======================
def test_admin_enrolls_student(auth_client, admin, student):
    course = CourseFactory()
    response = auth_client(admin).post(
        students_url(course), {"student_id": str(student.id)}, format="json"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["student"]["id"] == str(student.id)


def test_enroll_duplicate_returns_409(auth_client, admin):
    enrollment = EnrollmentFactory()
    response = auth_client(admin).post(
        students_url(enrollment.course), {"student_id": str(enrollment.student_id)}, format="json"
    )
    assert response.status_code == 409


def test_enroll_reactivates_removed_enrollment(auth_client, admin):
    enrollment = EnrollmentFactory(status=EnrollmentStatus.REMOVED)
    response = auth_client(admin).post(
        students_url(enrollment.course), {"student_id": str(enrollment.student_id)}, format="json"
    )
    assert response.status_code == 201
    assert response.json()["id"] == str(enrollment.id)
    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.ACTIVE
    assert Enrollment.objects.count() == 1


def test_cannot_enroll_teacher_or_inactive_student(auth_client, admin, teacher):
    course = CourseFactory()
    client = auth_client(admin)

    response = client.post(students_url(course), {"student_id": str(teacher.id)}, format="json")
    assert response.status_code == 422

    inactive = StudentFactory(status=UserStatus.INACTIVE)
    response = client.post(students_url(course), {"student_id": str(inactive.id)}, format="json")
    assert response.status_code == 400


def test_remove_enrollment_is_soft_and_idempotent(auth_client, admin):
    enrollment = EnrollmentFactory()
    client = auth_client(admin)
    url = f"{students_url(enrollment.course)}/{enrollment.id}"

    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 204
    enrollment.refresh_from_db()
    assert enrollment.status == EnrollmentStatus.REMOVED


def test_update_enrollment_status(auth_client, admin):
    enrollment = EnrollmentFactory()
    client = auth_client(admin)
    url = f"{students_url(enrollment.course)}/{enrollment.id}"

    response = client.patch(url, {"status": "COMPLETED"}, format="json")
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"

    assert client.patch(url, {"status": "NOPE"}, format="json").status_code == 422


def test_enrollment_list_hides_removed_by_default(auth_client, admin):
    course = CourseFactory()
    active = EnrollmentFactory(course=course)
    EnrollmentFactory(course=course, status=EnrollmentStatus.REMOVED)
    client = auth_client(admin)

    default = client.get(students_url(course)).json()["data"]
    assert [e["id"] for e in default] == [str(active.id)]

    removed = client.get(students_url(course), {"status": "REMOVED"}).json()["data"]
    assert len(removed) == 1 and removed[0]["status"] == "REMOVED"


def test_enrollment_search(auth_client, admin):
    course = CourseFactory()
    EnrollmentFactory(course=course, student=StudentFactory(full_name="Sardor Aliyev"))
    EnrollmentFactory(course=course, student=StudentFactory(full_name="Malika Karimova"))
    data = auth_client(admin).get(students_url(course), {"search": "sardor"}).json()["data"]
    assert [e["student"]["full_name"] for e in data] == ["Sardor Aliyev"]


def test_assigned_teacher_can_list_students_but_not_enroll(auth_client, teacher, student):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    EnrollmentFactory(course=course)
    client = auth_client(teacher)

    assert client.get(students_url(course)).json()["pagination"]["total"] == 1
    response = client.post(students_url(course), {"student_id": str(student.id)}, format="json")
    assert response.status_code == 403


def test_unassigned_teacher_gets_404_on_course_students(auth_client, teacher):
    assert auth_client(teacher).get(students_url(CourseFactory())).status_code == 404


def test_student_cannot_list_course_students(auth_client, student):
    course = CourseFactory()
    EnrollmentFactory(course=course, student=student)
    assert auth_client(student).get(students_url(course)).status_code == 403

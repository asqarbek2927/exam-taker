import pytest

from apps.academics.choices import CourseStatus, EnrollmentStatus, GroupStatus
from apps.academics.models import GroupStudent, StudyGroup
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    GroupStudentFactory,
    StudyGroupFactory,
)
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db


def groups_url(course, group=None):
    base = f"/api/v1/courses/{course.id}/groups"
    return f"{base}/{group.id}" if group else base


def members_url(course, group, student=None):
    base = f"{groups_url(course, group)}/students"
    return f"{base}/{student.id}" if student else base


def enrolled_student(course, **kwargs):
    return EnrollmentFactory(course=course, student=StudentFactory(**kwargs)).student


# ---------------------------- groups CRUD ----------------------------
def test_admin_creates_updates_and_deletes_group(auth_client, admin):
    course = CourseFactory()
    client = auth_client(admin)

    created = client.post(groups_url(course), {"name": "G-101"}, format="json")
    assert created.status_code == 201
    assert created.json()["students_count"] == 0
    group = StudyGroup.objects.get(pk=created.json()["id"])

    renamed = client.patch(groups_url(course, group), {"name": "G-102"}, format="json")
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "G-102"

    assert client.delete(groups_url(course, group)).status_code == 204
    assert not StudyGroup.objects.filter(pk=group.pk).exists()


def test_group_name_must_be_unique_within_course(auth_client, admin):
    course = CourseFactory()
    StudyGroupFactory(course=course, name="G-1")
    other = StudyGroupFactory(course=course, name="G-2")
    client = auth_client(admin)

    assert client.post(groups_url(course), {"name": "G-1"}, format="json").status_code == 409
    assert (
        client.patch(groups_url(course, other), {"name": "G-1"}, format="json").status_code == 409
    )
    # Boshqa kursda xuddi shu nom mumkin.
    other_course = CourseFactory()
    assert client.post(groups_url(other_course), {"name": "G-1"}, format="json").status_code == 201


def test_group_name_is_required(auth_client, admin):
    response = auth_client(admin).post(groups_url(CourseFactory()), {}, format="json")
    assert response.status_code == 422


def test_assigned_teacher_reads_but_cannot_write(auth_client, teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    group = StudyGroupFactory(course=course)
    client = auth_client(teacher)

    assert client.get(groups_url(course)).status_code == 200
    assert client.get(groups_url(course, group)).status_code == 200
    assert client.post(groups_url(course), {"name": "X"}, format="json").status_code == 403
    assert client.patch(groups_url(course, group), {"name": "Y"}, format="json").status_code == 403
    assert client.delete(groups_url(course, group)).status_code == 403


def test_unassigned_teacher_gets_404_and_student_gets_403(auth_client, teacher, student):
    course = CourseFactory()
    assert auth_client(teacher).get(groups_url(course)).status_code == 404
    EnrollmentFactory(course=course, student=student)
    assert auth_client(student).get(groups_url(course)).status_code == 403


def test_group_of_another_course_is_not_reachable(auth_client, admin):
    course = CourseFactory()
    foreign = StudyGroupFactory()
    assert auth_client(admin).get(groups_url(course, foreign)).status_code == 404


def test_list_shows_students_count(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    GroupStudentFactory.create_batch(3, group=group)
    StudyGroupFactory(course=course)

    data = auth_client(admin).get(groups_url(course)).json()["data"]
    counts = {g["id"]: g["students_count"] for g in data}
    assert counts[str(group.id)] == 3
    assert sorted(counts.values()) == [0, 3]


def test_delete_group_removes_memberships_only(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    membership = GroupStudentFactory(group=group)
    student = membership.student

    assert auth_client(admin).delete(groups_url(course, group)).status_code == 204
    assert not GroupStudent.objects.filter(pk=membership.pk).exists()
    student.refresh_from_db()  # student o‘chmaydi


def test_archived_course_blocks_group_changes(auth_client, admin):
    course = CourseFactory(status=CourseStatus.ARCHIVED)
    group = StudyGroupFactory(course=course)
    client = auth_client(admin)
    assert client.post(groups_url(course), {"name": "X"}, format="json").status_code == 400
    assert client.patch(groups_url(course, group), {"name": "Y"}, format="json").status_code == 400
    assert client.delete(groups_url(course, group)).status_code == 400


# ---------------------------- group students ----------------------------
def test_add_enrolled_student_to_group(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    student = enrolled_student(course)

    response = auth_client(admin).post(
        members_url(course, group), {"student_id": str(student.id)}, format="json"
    )
    assert response.status_code == 201
    assert response.json()["student"]["id"] == str(student.id)
    assert GroupStudent.objects.filter(group=group, student=student).exists()


def test_cannot_add_student_who_is_not_actively_enrolled(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    client = auth_client(admin)

    stranger = StudentFactory()
    response = client.post(
        members_url(course, group), {"student_id": str(stranger.id)}, format="json"
    )
    assert response.status_code == 400

    removed = EnrollmentFactory(course=course, status=EnrollmentStatus.REMOVED).student
    response = client.post(
        members_url(course, group), {"student_id": str(removed.id)}, format="json"
    )
    assert response.status_code == 400


def test_cannot_add_student_twice_or_non_student(auth_client, admin, teacher):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    student = enrolled_student(course)
    client = auth_client(admin)
    body = {"student_id": str(student.id)}

    assert client.post(members_url(course, group), body, format="json").status_code == 201
    assert client.post(members_url(course, group), body, format="json").status_code == 409
    teacher_body = {"student_id": str(teacher.id)}
    assert client.post(members_url(course, group), teacher_body, format="json").status_code == 422


def test_list_and_search_group_students(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    GroupStudentFactory(group=group, student=StudentFactory(full_name="Sardor Aliyev"))
    GroupStudentFactory(group=group, student=StudentFactory(full_name="Malika Karimova"))
    client = auth_client(admin)

    assert client.get(members_url(course, group)).json()["pagination"]["total"] == 2
    found = client.get(members_url(course, group), {"search": "malika"}).json()["data"]
    assert [m["student"]["full_name"] for m in found] == ["Malika Karimova"]


def test_assigned_teacher_can_list_members_but_not_modify(auth_client, teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    group = StudyGroupFactory(course=course)
    membership = GroupStudentFactory(group=group)
    client = auth_client(teacher)

    assert client.get(members_url(course, group)).status_code == 200
    assert client.delete(members_url(course, group, membership.student)).status_code == 403


def test_remove_student_from_group(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    membership = GroupStudentFactory(group=group)
    client = auth_client(admin)

    assert client.delete(members_url(course, group, membership.student)).status_code == 204
    assert not GroupStudent.objects.filter(pk=membership.pk).exists()
    assert client.delete(members_url(course, group, membership.student)).status_code == 404


def test_removing_enrollment_drops_group_memberships_in_that_course(auth_client, admin):
    course = CourseFactory()
    other_course = CourseFactory()
    group = StudyGroupFactory(course=course)
    other_group = StudyGroupFactory(course=other_course)
    enrollment = EnrollmentFactory(course=course)
    student = enrollment.student
    GroupStudentFactory(group=group, student=student)
    GroupStudentFactory(group=other_group, student=student)

    url = f"/api/v1/courses/{course.id}/students/{enrollment.id}"
    assert auth_client(admin).delete(url).status_code == 204

    assert not GroupStudent.objects.filter(group=group, student=student).exists()
    assert GroupStudent.objects.filter(group=other_group, student=student).exists()


def test_marking_enrollment_removed_or_completed(auth_client, admin):
    course = CourseFactory()
    group = StudyGroupFactory(course=course)
    enrollment = EnrollmentFactory(course=course)
    GroupStudentFactory(group=group, student=enrollment.student)
    url = f"/api/v1/courses/{course.id}/students/{enrollment.id}"
    client = auth_client(admin)

    client.patch(url, {"status": "COMPLETED"}, format="json")
    assert GroupStudent.objects.filter(group=group, student=enrollment.student).exists()

    client.patch(url, {"status": "REMOVED"}, format="json")
    assert not GroupStudent.objects.filter(group=group, student=enrollment.student).exists()


# ---------------------------- global group directory ----------------------------
def test_admin_creates_group_with_teaching_pair(auth_client, admin):
    course = CourseFactory()
    main = CourseTeacherFactory(course=course).teacher
    support = CourseTeacherFactory(course=course, type="SUPPORT").teacher

    response = auth_client(admin).post(
        "/api/v1/groups",
        {
            "course_id": str(course.id),
            "name": "Frontend A",
            "main_teacher_id": str(main.id),
            "support_teacher_id": str(support.id),
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["course"] == {"id": str(course.id), "name": course.name}
    assert response.json()["main_teacher"]["id"] == str(main.id)
    assert response.json()["support_teacher"]["id"] == str(support.id)
    assert response.json()["status"] == "ACTIVE"


def test_group_teacher_must_be_active_and_assigned_to_course(auth_client, admin):
    course = CourseFactory()
    stranger = TeacherFactory()
    response = auth_client(admin).post(
        "/api/v1/groups",
        {
            "course_id": str(course.id),
            "name": "Frontend A",
            "main_teacher_id": str(stranger.id),
        },
        format="json",
    )
    assert response.status_code == 400

    assigned = CourseTeacherFactory(course=course).teacher
    same = auth_client(admin).post(
        "/api/v1/groups",
        {
            "course_id": str(course.id),
            "name": "Frontend B",
            "main_teacher_id": str(assigned.id),
            "support_teacher_id": str(assigned.id),
        },
        format="json",
    )
    assert same.status_code == 400


def test_group_directory_list_filters_and_student_preview(auth_client, admin):
    course = CourseFactory(name="Frontend development")
    group = StudyGroupFactory(course=course, name="Frontend A")
    students = [enrolled_student(course) for _ in range(4)]
    for student in students:
        GroupStudentFactory(group=group, student=student)
    StudyGroupFactory(status=GroupStatus.ARCHIVED)

    response = auth_client(admin).get(
        "/api/v1/groups",
        {"course_id": str(course.id), "status": "ACTIVE", "search": "frontend"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["id"] for item in data] == [str(group.id)]
    assert data[0]["students_count"] == 4
    assert len(data[0]["students_preview"]) == 3


def test_group_directory_summary_counts_unique_students(auth_client, admin):
    course = CourseFactory()
    main = CourseTeacherFactory(course=course).teacher
    support = CourseTeacherFactory(course=course, type="SUPPORT").teacher
    first = StudyGroupFactory(course=course, main_teacher=main, support_teacher=support)
    second = StudyGroupFactory(course=course)
    StudyGroupFactory(status=GroupStatus.ARCHIVED)
    shared = enrolled_student(course)
    first_only = enrolled_student(course)
    GroupStudentFactory(group=first, student=shared)
    GroupStudentFactory(group=first, student=first_only)
    GroupStudentFactory(group=second, student=shared)

    response = auth_client(admin).get("/api/v1/groups/summary")

    assert response.status_code == 200
    assert response.json() == {
        "active_groups": 2,
        "grouped_students": 2,
        "teaching_pairs": 1,
        "archived_groups": 1,
    }


def test_group_archive_restore_and_read_only_rule(auth_client, admin):
    group = StudyGroupFactory()
    client = auth_client(admin)

    archived = client.post(f"/api/v1/groups/{group.id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"
    assert (
        client.patch(f"/api/v1/groups/{group.id}", {"name": "Blocked"}, format="json").status_code
        == 400
    )

    restored = client.post(f"/api/v1/groups/{group.id}/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "ACTIVE"


def test_group_directory_is_scoped_for_teacher(auth_client, teacher):
    response = auth_client(teacher).get("/api/v1/groups")
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert auth_client(teacher).get("/api/v1/groups/summary").status_code == 403

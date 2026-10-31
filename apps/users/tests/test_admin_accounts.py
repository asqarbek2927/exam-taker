from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.academics.choices import CourseTeacherType
from apps.academics.models import CourseTeacher
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    StudyGroupFactory,
)
from apps.attempts.tests.factories import AttemptFactory
from apps.audit.choices import AuditAction
from apps.audit.models import AuditLog
from apps.exams.tests.factories import ExamFactory
from apps.users.choices import UserStatus
from apps.users.models import User
from apps.users.tests.factories import (
    DEFAULT_PASSWORD,
    AdminFactory,
    StudentFactory,
    SupportTeacherFactory,
    TeacherFactory,
)

pytestmark = pytest.mark.django_db

ACCOUNTS = "/api/v1/admin/accounts"


def create_payload(**overrides):
    payload = {
        "full_name": "Madina Karimova",
        "email": "madina@example.com",
        "role": "STUDENT",
        "phone_number": "+998901234567",
        "location": "Tashkent",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("fixture_name", ["teacher", "student"])
def test_admin_accounts_requires_super_admin(request, auth_client, fixture_name):
    response = auth_client(request.getfixturevalue(fixture_name)).get(ACCOUNTS)
    assert response.status_code == 403


def test_create_returns_one_time_credentials_and_audits(auth_client, admin):
    response = auth_client(admin).post(ACCOUNTS, create_payload(), format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["account"]["email"] == "madina@example.com"
    assert body["account"]["must_change_password"] is True
    assert body["account"]["version"] == 1
    assert body["temporary_password"]
    assert body["temporary_password_expires_at"]

    user = User.objects.get(pk=body["account"]["id"])
    assert user.check_password(body["temporary_password"])
    assert user.phone_number == "+998901234567"
    assert user.location == "Tashkent"
    assert user.temporary_password_expires_at > timezone.now() + timedelta(hours=23)
    assert AuditLog.objects.filter(entity_id=user.pk, action=AuditAction.ACCOUNT_CREATED).exists()


@pytest.mark.parametrize("role", ["TEACHER", "SUPPORT_TEACHER", "STUDENT"])
def test_create_returns_top_level_temporary_password_for_every_role(auth_client, admin, role):
    response = auth_client(admin).post(
        ACCOUNTS,
        create_payload(email=f"{role.lower()}@example.com", role=role),
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["account"]["role"] == role
    assert body["temporary_password"]
    assert body["temporary_password_expires_at"]
    user = User.objects.get(pk=body["account"]["id"])
    assert user.check_password(body["temporary_password"])


def test_create_rejects_password_and_assignment_fields(auth_client, admin):
    payload = create_payload(password=DEFAULT_PASSWORD, course_ids=[])
    response = auth_client(admin).post(ACCOUNTS, payload, format="json")
    assert response.status_code == 422
    assert {"password", "course_ids"}.issubset(response.json()["errors"])


def test_create_support_teacher_and_list_summary(auth_client, admin):
    created = auth_client(admin).post(
        ACCOUNTS,
        create_payload(
            email="support-new@example.com",
            role="SUPPORT_TEACHER",
            phone_number="",
        ),
        format="json",
    )
    assert created.status_code == 201
    assert created.json()["account"]["role"] == "SUPPORT_TEACHER"

    response = auth_client(admin).get(ACCOUNTS, {"role": "SUPPORT_TEACHER"})
    assert response.status_code == 200
    assert [item["role"] for item in response.json()["data"]] == ["SUPPORT_TEACHER"]
    assert response.json()["summary"]["support_teachers"] == 1


def test_list_teacher_accounts_contains_distinct_stats_and_filters_by_course(auth_client, admin):
    teacher = TeacherFactory(full_name="Teacher With Stats")
    support = SupportTeacherFactory(full_name="Support With Stats")
    first_course = CourseFactory(name="First course")
    second_course = CourseFactory(name="Second course")
    CourseTeacherFactory(teacher=teacher, course=first_course)
    CourseTeacherFactory(teacher=teacher, course=second_course)
    CourseTeacherFactory(
        teacher=support,
        course=first_course,
        type=CourseTeacherType.SUPPORT,
    )
    student = StudentFactory()
    EnrollmentFactory(course=first_course, student=student)
    EnrollmentFactory(course=second_course, student=student)
    ExamFactory.create_batch(2, course=first_course, created_by=teacher)
    ExamFactory(course=second_course, created_by=teacher)

    response = auth_client(admin).get(
        ACCOUNTS,
        {
            "role": "TEACHER",
            "course_id": str(second_course.id),
            "search": "Teacher With Stats",
            "ordering": "-exams_count",
            "page": 1,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    body = response.json()["data"][0]
    assert body["id"] == str(teacher.id)
    assert body["assigned_courses"] == [
        {"id": str(first_course.id), "name": "First course"},
        {"id": str(second_course.id), "name": "Second course"},
    ]
    assert body["courses_count"] == 2
    assert body["students_count"] == 1
    assert body["exams_count"] == 3


@pytest.mark.parametrize("role", ["TEACHER", "SUPPORT_TEACHER"])
def test_account_summary_is_role_scoped_and_not_paginated(auth_client, admin, role):
    active_teacher = TeacherFactory()
    TeacherFactory(status=UserStatus.INACTIVE)
    support = SupportTeacherFactory()
    first_course = CourseFactory()
    second_course = CourseFactory()
    CourseTeacherFactory(teacher=active_teacher, course=first_course)
    CourseTeacherFactory(teacher=active_teacher, course=second_course)
    CourseTeacherFactory(
        teacher=support,
        course=first_course,
        type=CourseTeacherType.SUPPORT,
    )
    student = StudentFactory()
    EnrollmentFactory(course=first_course, student=student)
    EnrollmentFactory(course=second_course, student=student)

    response = auth_client(admin).get(f"{ACCOUNTS}/summary", {"role": role, "limit": 1})

    assert response.status_code == 200
    expected = {
        "TEACHER": {
            "total_accounts": 2,
            "active_accounts": 1,
            "inactive_accounts": 1,
            "students_taught": 1,
            "course_assignments": 2,
        },
        "SUPPORT_TEACHER": {
            "total_accounts": 1,
            "active_accounts": 1,
            "inactive_accounts": 0,
            "students_taught": 1,
            "course_assignments": 1,
        },
    }
    assert response.json() == expected[role]


@pytest.mark.parametrize("params", [{}, {"role": "STUDENT"}])
def test_account_summary_requires_educator_role(auth_client, admin, params):
    response = auth_client(admin).get(f"{ACCOUNTS}/summary", params)
    assert response.status_code == 422
    assert "role" in response.json()["errors"]


def test_detail_contains_role_specific_courses_groups_and_stats(auth_client, admin):
    teacher = TeacherFactory()
    course = CourseFactory()
    CourseTeacherFactory(teacher=teacher, course=course)
    group = StudyGroupFactory(course=course, main_teacher=teacher)

    response = auth_client(admin).get(f"{ACCOUNTS}/{teacher.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["courses"][0]["id"] == str(course.id)
    assert body["courses"][0]["teacher_type"] == "MAIN"
    assert body["groups"][0]["id"] == str(group.id)
    assert set(body["exam_stats"]) == {
        "created_exams",
        "published_assignments",
        "graded_attempts",
    }


def test_patch_is_versioned_and_updates_email(auth_client, admin, teacher):
    client = auth_client(admin)
    email_updated = client.patch(
        f"{ACCOUNTS}/{teacher.id}",
        {"email": "changed@example.com", "version": teacher.version},
        format="json",
    )
    assert email_updated.status_code == 200
    assert email_updated.json()["email"] == "changed@example.com"
    assert email_updated.json()["version"] == 2

    updated = client.patch(
        f"{ACCOUNTS}/{teacher.id}",
        {"full_name": "Updated Teacher", "location": "Samarkand", "version": 2},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 3

    conflict = client.patch(
        f"{ACCOUNTS}/{teacher.id}",
        {"full_name": "Stale", "version": 1},
        format="json",
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize("target_factory", [TeacherFactory, SupportTeacherFactory, StudentFactory])
def test_put_updates_admin_account_avatar(auth_client, admin, target_factory, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    target = target_factory()
    image = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(image, format="PNG")
    avatar = SimpleUploadedFile("teacher.png", image.getvalue(), content_type="image/png")

    response = auth_client(admin).put(
        f"{ACCOUNTS}/{target.id}",
        {"avatar": avatar, "version": target.version},
        format="multipart",
    )

    assert response.status_code == 200
    assert "/media/avatars/" in response.json()["avatar_url"]
    assert response.json()["version"] == 2
    target.refresh_from_db()
    assert target.avatar.name.endswith(".png")


@pytest.mark.parametrize("target_factory", [TeacherFactory, SupportTeacherFactory, StudentFactory])
def test_admin_deletes_managed_account_avatar(
    auth_client,
    admin,
    target_factory,
    settings,
    tmp_path,
    django_capture_on_commit_callbacks,
):
    settings.MEDIA_ROOT = tmp_path
    image = BytesIO()
    Image.new("RGB", (2, 2), color="red").save(image, format="PNG")
    target = target_factory(
        avatar=SimpleUploadedFile("avatar.png", image.getvalue(), content_type="image/png")
    )
    stored_path = tmp_path / target.avatar.name
    assert stored_path.exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client(admin).delete(
            f"{ACCOUNTS}/{target.id}/photo?version={target.version}",
        )

    assert response.status_code == 200
    assert response.json()["avatar_url"] == ""
    assert response.json()["version"] == 2
    target.refresh_from_db()
    assert not target.avatar
    assert not stored_path.exists()
    assert AuditLog.objects.filter(
        entity_id=target.pk,
        action=AuditAction.ACCOUNT_UPDATED,
        metadata__changed_fields=["avatar"],
    ).exists()


def test_admin_cannot_delete_another_super_admin_avatar(auth_client, admin):
    target = AdminFactory()
    response = auth_client(admin).delete(
        f"{ACCOUNTS}/{target.id}/photo?version={target.version}",
    )
    assert response.status_code == 400


def test_non_admin_cannot_delete_account_avatar(auth_client, teacher):
    target = StudentFactory()
    response = auth_client(teacher).delete(
        f"{ACCOUNTS}/{target.id}/photo?version={target.version}",
    )
    assert response.status_code == 403


def test_patch_rejects_duplicate_email(auth_client, admin, teacher):
    existing = TeacherFactory()
    response = auth_client(admin).patch(
        f"{ACCOUNTS}/{teacher.id}",
        {"email": existing.email, "version": teacher.version},
        format="json",
    )
    assert response.status_code == 422
    assert "email" in response.json()["errors"]


def test_status_change_revokes_sessions_and_deleted_cannot_restore(
    api_client, auth_client, admin, teacher
):
    login = api_client.post(
        "/api/v1/auth/login",
        {"email": teacher.email, "password": DEFAULT_PASSWORD},
        format="json",
    ).json()
    response = auth_client(admin).put(
        f"{ACCOUNTS}/{teacher.id}/status",
        {"status": "INACTIVE", "version": teacher.version},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"
    assert BlacklistedToken.objects.filter(token__user=teacher).exists()
    assert (
        api_client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": login["refresh_token"]},
            format="json",
        ).status_code
        == 401
    )


def test_soft_delete_preserves_history_and_blocks_login(api_client, auth_client, admin):
    attempt = AttemptFactory()
    student = attempt.student
    response = auth_client(admin).delete(
        f"{ACCOUNTS}/{student.id}", {"version": student.version}, format="json"
    )
    assert response.status_code == 204
    student.refresh_from_db()
    assert student.status == UserStatus.DELETED
    assert student.deleted_at is not None
    assert type(attempt).objects.filter(pk=attempt.pk).exists()
    assert (
        api_client.post(
            "/api/v1/auth/login",
            {"email": student.email, "password": DEFAULT_PASSWORD},
            format="json",
        ).status_code
        == 401
    )


def test_soft_delete_rejects_active_group_main_teacher(auth_client, admin, teacher):
    StudyGroupFactory(main_teacher=teacher)
    response = auth_client(admin).delete(
        f"{ACCOUNTS}/{teacher.id}", {"version": teacher.version}, format="json"
    )
    assert response.status_code == 409


def test_temporary_password_is_one_time_response_and_revokes_old_session(
    api_client, auth_client, admin, teacher
):
    tokens = api_client.post(
        "/api/v1/auth/login",
        {"email": teacher.email, "password": DEFAULT_PASSWORD},
        format="json",
    ).json()
    response = auth_client(admin).post(f"{ACCOUNTS}/{teacher.id}/temporary-password")
    assert response.status_code == 200
    password = response.json()["temporary_password"]
    teacher.refresh_from_db()
    assert teacher.must_change_password is True
    assert teacher.check_password(password)
    assert BlacklistedToken.objects.filter(token__user=teacher).exists()
    assert (
        api_client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": tokens["refresh_token"]},
            format="json",
        ).status_code
        == 401
    )
    detail = auth_client(admin).get(f"{ACCOUNTS}/{teacher.id}").json()
    assert "temporary_password" not in detail


def test_courses_endpoint_supports_student_and_teacher(auth_client, admin):
    teacher_assignment = CourseTeacherFactory()
    enrollment = EnrollmentFactory()
    student_teacher = TeacherFactory(full_name="Aziz Rahimov")
    CourseTeacherFactory(course=enrollment.course, teacher=student_teacher)
    client = auth_client(admin)

    teacher_courses = client.get(f"{ACCOUNTS}/{teacher_assignment.teacher_id}/courses").json()
    student_courses = client.get(f"{ACCOUNTS}/{enrollment.student_id}/courses").json()
    assert teacher_courses[0]["teacher_type"] == "MAIN"
    assert student_courses[0]["status"] == "ACTIVE"
    assert student_courses[0]["teacher_name"] == "Aziz Rahimov"
    assert student_courses[0]["progress"] is None


def test_student_course_teacher_name_is_null_without_teacher(auth_client, admin):
    enrollment = EnrollmentFactory()

    response = auth_client(admin).get(f"{ACCOUNTS}/{enrollment.student_id}/courses")

    assert response.status_code == 200
    assert response.json()[0]["teacher_name"] is None
    assert response.json()[0]["progress"] is None


def test_student_course_uses_support_teacher_when_main_is_missing(auth_client, admin):
    enrollment = EnrollmentFactory()
    support = SupportTeacherFactory(full_name="Support Teacher")
    CourseTeacherFactory(
        course=enrollment.course,
        teacher=support,
        type=CourseTeacherType.SUPPORT,
    )

    response = auth_client(admin).get(f"{ACCOUNTS}/{enrollment.student_id}/courses")

    assert response.status_code == 200
    assert response.json()[0]["teacher_name"] == "Support Teacher"


def test_replace_teaching_courses_and_support_teacher_rule(auth_client, admin):
    teacher = TeacherFactory()
    first = CourseFactory()
    second = CourseFactory()
    CourseTeacherFactory(teacher=teacher, course=first)
    response = auth_client(admin).put(
        f"{ACCOUNTS}/{teacher.id}/teaching-courses",
        {
            "course_ids": [str(second.id)],
            "main_course_ids": [str(second.id)],
            "version": teacher.version,
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(second.id),
            "name": second.name,
            "status": "ACTIVE",
            "teacher_type": "MAIN",
            "groups_count": 0,
            "students_count": 0,
        }
    ]
    assert not CourseTeacher.objects.filter(teacher=teacher, course=first).exists()

    support = SupportTeacherFactory()
    rejected = auth_client(admin).put(
        f"{ACCOUNTS}/{support.id}/teaching-courses",
        {
            "course_ids": [str(first.id)],
            "main_course_ids": [str(first.id)],
            "version": support.version,
        },
        format="json",
    )
    assert rejected.status_code == 400

    accepted = auth_client(admin).put(
        f"{ACCOUNTS}/{support.id}/teaching-courses",
        {"course_ids": [str(first.id)], "main_course_ids": [], "version": support.version},
        format="json",
    )
    assert accepted.status_code == 200
    assert accepted.json()[0]["teacher_type"] == CourseTeacherType.SUPPORT


def test_activity_is_real_paged_audit_log(auth_client, admin, teacher):
    client = auth_client(admin)
    client.patch(
        f"{ACCOUNTS}/{teacher.id}",
        {"location": "Bukhara", "version": teacher.version},
        format="json",
    )
    response = client.get(f"{ACCOUNTS}/{teacher.id}/activity")
    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    assert response.json()["data"][0]["action"] == AuditAction.ACCOUNT_UPDATED


def test_support_teacher_uses_educator_scoped_apis(auth_client):
    support = SupportTeacherFactory()
    course = CourseFactory()
    CourseTeacherFactory(
        teacher=support,
        course=course,
        type=CourseTeacherType.SUPPORT,
    )
    client = auth_client(support)

    assert client.get("/api/v1/courses").status_code == 200
    assert client.get("/api/v1/questions").status_code == 200
    assert client.get("/api/v1/exams").status_code == 200
    assert client.get("/api/v1/exam-assignments").status_code == 200
    assert client.get("/api/v1/teacher/dashboard").status_code == 200

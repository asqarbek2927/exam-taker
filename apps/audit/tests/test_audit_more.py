"""Qo'shimcha audit yozuvlari: login, natijalarni o'chirish, savol/imtihon o'zgarishlari, import."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.academics.tests.factories import CourseFactory, CourseTeacherFactory, ModuleFactory
from apps.audit.choices import AuditAction
from apps.audit.models import AuditLog
from apps.exams.tests.factories import ExamFactory
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import DEFAULT_PASSWORD, StudentFactory

pytestmark = pytest.mark.django_db
OPTIONS = [{"text": "A javob", "is_correct": True}, {"text": "B javob", "is_correct": False}]


def _log(action):
    return AuditLog.objects.filter(action=action)


@pytest.fixture
def ctx(teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    return {"course": course, "module": ModuleFactory(course=course), "teacher": teacher}


# ------------------------------------ login ---------------------------------
def test_successful_login_is_audited_with_ip_and_device():
    user = StudentFactory()
    client = APIClient(REMOTE_ADDR="10.9.8.7", HTTP_USER_AGENT="Mozilla/5.0 TestBrowser")
    response = client.post(
        "/api/v1/auth/login",
        {"username_or_email": user.username, "password": DEFAULT_PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    (entry,) = _log(AuditAction.LOGIN_SUCCEEDED)
    assert entry.actor == user and entry.entity_type == "session" and entry.entity_id == user.pk
    assert entry.metadata == {"ip": "10.9.8.7", "user_agent": "Mozilla/5.0 TestBrowser"}


def test_failed_login_is_not_audited_as_success():
    user = StudentFactory()
    APIClient().post(
        "/api/v1/auth/login",
        {"username_or_email": user.username, "password": "Wrong-Pass1"},
        format="json",
    )
    assert not _log(AuditAction.LOGIN_SUCCEEDED).exists()


def test_logins_do_not_flood_admin_account_activity(auth_client, admin):
    """Admin panelidagi akkaunt faoliyati (`entity_type=account`) loginlar bilan to'lmaydi."""
    user = StudentFactory()
    APIClient().post(
        "/api/v1/auth/login",
        {"username_or_email": user.username, "password": DEFAULT_PASSWORD},
        format="json",
    )
    body = auth_client(admin).get(f"/api/v1/admin/accounts/{user.id}/activity").json()
    assert body["data"] == []


# -------------------------------- questions ---------------------------------
def test_question_update_records_changed_fields_but_not_answer_key(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"],
        module=ctx["module"],
        created_by=ctx["teacher"],
        options=[
            ("Eski", True),
            ("Boshqa", False),
        ],
    )
    response = auth_client(ctx["teacher"]).patch(
        f"/api/v1/questions/{question.id}",
        {"text": "Yangi matn", "options": OPTIONS},
        format="json",
    )
    assert response.status_code == 200, response.json()
    (entry,) = _log(AuditAction.QUESTION_UPDATED)
    assert entry.actor == ctx["teacher"]
    assert entry.metadata["changed_fields"] == ["options", "text"]
    assert entry.metadata["question_text"] == "Yangi matn"
    dumped = json.dumps(entry.metadata, ensure_ascii=False)
    assert "A javob" not in dumped and "is_correct" not in dumped  # answer key yozilmaydi


def test_invalid_question_update_is_not_audited(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    response = auth_client(ctx["teacher"]).patch(
        f"/api/v1/questions/{question.id}", {"text": ""}, format="json"
    )
    assert response.status_code >= 400
    assert not _log(AuditAction.QUESTION_UPDATED).exists()


def test_question_delete_archive_restore_are_audited(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    doomed = QuestionFactory(course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"])
    doomed_id, doomed_text = doomed.id, doomed.text
    assert client.delete(f"/api/v1/questions/{doomed_id}").status_code == 204
    (deleted,) = _log(AuditAction.QUESTION_DELETED)
    assert deleted.entity_id == doomed_id and deleted.metadata["archived"] is False
    assert deleted.metadata["question_text"] == doomed_text[:200]

    kept = QuestionFactory(course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"])
    assert client.post(f"/api/v1/questions/{kept.id}/archive").status_code == 200
    assert client.post(f"/api/v1/questions/{kept.id}/restore").status_code == 200
    assert (
        _log(AuditAction.QUESTION_DELETED).filter(entity_id=kept.id).get().metadata["archived"]
        is True
    )
    assert _log(AuditAction.QUESTION_RESTORED).filter(entity_id=kept.id).exists()


def test_question_import_is_audited(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    template = json.loads(
        client.get(
            "/api/v1/questions/import-template-json",
            {"course_id": ctx["course"].id, "module_id": ctx["module"].id},
        ).content
    )
    template["questions"] = [
        {"type": "OPEN_ENDED", "text": f"Q{i}", "options": [], "correct": [], "points": 5}
        for i in range(3)
    ]
    upload = SimpleUploadedFile("savollar.json", json.dumps(template).encode())
    response = client.post("/api/v1/questions/import", {"file": upload}, format="multipart")
    assert response.status_code == 201, response.json()
    (entry,) = _log(AuditAction.QUESTIONS_IMPORTED)
    assert entry.entity_id == ctx["module"].id
    assert entry.metadata["count"] == 3
    assert entry.metadata["format"] == "json" and entry.metadata["file_name"] == "savollar.json"


# ---------------------------------- exams -----------------------------------
def test_exam_update_and_delete_are_audited(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    exam = ExamFactory(course=ctx["course"], created_by=ctx["teacher"])
    response = client.patch(f"/api/v1/exams/{exam.id}", {"title": "Yangi nom"}, format="json")
    assert response.status_code == 200, response.json()
    (updated,) = _log(AuditAction.EXAM_UPDATED)
    assert updated.metadata["changed_fields"] == ["title"]
    assert updated.metadata["title"] == "Yangi nom"

    exam_id = exam.id
    assert client.delete(f"/api/v1/exams/{exam_id}").status_code in (200, 204)
    (deleted,) = _log(AuditAction.EXAM_DELETED)
    assert deleted.entity_id == exam_id and deleted.actor == ctx["teacher"]

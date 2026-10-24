from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.academics.models import Course, GroupStudent
from apps.assignments.models import ExamAssignment
from apps.attempts.models import ExamAttempt
from apps.questions.models import Question
from apps.reports.management.commands.seed_demo import ADMIN_EMAIL, DEFAULT_PASSWORD
from apps.users.models import User

pytestmark = pytest.mark.django_db


def seed(*args) -> str:
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def login(client, email):
    response = client.post(
        "/api/v1/auth/login", {"email": email, "password": DEFAULT_PASSWORD}, format="json"
    )
    assert response.status_code == 200, response.json()
    return {"HTTP_AUTHORIZATION": f"Bearer {response.json()['access_token']}"}


def test_refuses_to_run_outside_debug_without_the_flag():
    with pytest.raises(CommandError):
        seed()
    assert not User.objects.exists()


def test_creates_a_coherent_demo_world():
    output = seed("--allow-production")
    assert "Demo ma’lumotlar yaratildi" in output and DEFAULT_PASSWORD in output

    assert User.objects.count() == 1 + 2 + 6
    assert Course.objects.count() == 2
    assert GroupStudent.objects.count() == 5
    assert Question.objects.count() == 8
    assert ExamAssignment.objects.count() == 3
    statuses = sorted(ExamAssignment.objects.values_list("status", flat=True))
    assert statuses == ["PAUSED", "PUBLISHED", "PUBLISHED"]
    assert ExamAttempt.objects.count() == 3
    assert sorted(ExamAttempt.objects.values_list("status", flat=True)) == [
        "GRADED",
        "GRADED",
        "PENDING_GRADING",
    ]


def test_seed_is_idempotent():
    seed("--allow-production")
    output = seed("--allow-production")
    assert "allaqachon mavjud" in output
    assert User.objects.count() == 9


def test_demo_users_can_use_the_api_end_to_end(api_client):
    seed("--allow-production")
    admin = login(api_client, ADMIN_EMAIL)
    teacher = login(api_client, "teacher1@examtaker.local")
    student3 = login(api_client, "student3@examtaker.local")
    student2 = login(api_client, "student2@examtaker.local")

    # Teacher: 1 ta attempt qo‘lda baholashni kutmoqda.
    pending = api_client.get("/api/v1/grading/pending", **teacher).json()["data"]
    assert len(pending) == 1 and pending[0]["student"]["email"] == "student1@examtaker.local"
    detail = api_client.get(f"/api/v1/attempts/{pending[0]['id']}", **teacher).json()
    essay = next(a for a in detail["answers"] if a["question"]["type"] == "OPEN_ENDED")
    graded = api_client.patch(
        f"/api/v1/answers/{essay['id']}/grade",
        {"points_awarded": 4, "teacher_feedback": "Yaxshi"},
        format="json",
        **teacher,
    ).json()
    assert graded["attempt"]["status"] == "GRADED"

    # student2: "latest attempt" bo‘yicha o‘tgan; student3 hali boshlashi mumkin.
    results = api_client.get("/api/v1/results?latest_only=true", **student2).json()["data"]
    assert len(results) == 1 and results[0]["passed"] is True and results[0]["attempt_number"] == 2
    listing = api_client.get("/api/v1/exam-assignments", **student3).json()["data"]
    startable = [a for a in listing if a["can_start"]]
    assert len(startable) == 1
    started = api_client.post(f"/api/v1/exam-assignments/{startable[0]['id']}/start", **student3)
    assert started.status_code == 201

    dashboard = api_client.get("/api/v1/admin/dashboard", **admin).json()
    assert dashboard["total_students"] == 6 and dashboard["active_assignments"] == 1
    assert dashboard["average_score"] is not None

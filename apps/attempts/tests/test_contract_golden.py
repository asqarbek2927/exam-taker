"""Golden testlar: front ishlatadigan asosiy response shakllari o‘zgarmasligi kerak.

Har bir test haqiqiy oqimni (login -> start -> autosave -> event -> submit -> grade ->
results/dashboard) bajaradi va response'ning shaklini (kalitlar + tiplar) snapshot bilan
solishtiradi. Qiymatlar emas, faqat shakl tekshiriladi — refactor xavfsizligi uchun.
"""

import uuid

import pytest
from django.utils import timezone

from apps.assignments.choices import ResultReviewMode
from apps.attempts.models import StudentAnswer
from apps.attempts.tests.conftest import option_id
from apps.users.tests.factories import DEFAULT_PASSWORD
from common.tests.snapshot import assert_shape_snapshot

pytestmark = pytest.mark.django_db


def _ok(response, expected=200):
    assert response.status_code == expected, response.content
    return response.json()


@pytest.fixture
def flow(api, auth_client, admin, make_world):
    """Butun imtihon oqimi; har bir qadamning response'ini qaytaradi."""
    world = make_world(result_review_mode=ResultReviewMode.FULL_REVIEW, answer_review_released=True)
    student = api(world.student)
    q, eq = world.q, world.eq
    out = {}

    out["start"] = _ok(student.start(world.assignment), 201)
    attempt_id = out["start"]["id"]
    out["attempt_in_progress"] = _ok(student.detail(attempt_id))
    out["save_answer_choice"] = _ok(
        student.answer(attempt_id, eq["single"], option_ids=[option_id(q["single"], "Right")])
    )
    student.answer(attempt_id, eq["multi"], option_ids=[option_id(q["multi"], "R1")])
    student.answer(attempt_id, eq["tf"], option_ids=[option_id(q["tf"], "True")])
    out["save_answer_text"] = _ok(student.answer(attempt_id, eq["open"], text_answer="Essay"))
    out["event"] = _ok(
        student.client.post(
            f"/api/v1/attempts/{attempt_id}/events",
            {
                "event_id": str(uuid.uuid4()),
                "type": "TAB_HIDDEN",
                "client_at": timezone.now().isoformat(),
                "details": {"visibility_state": "hidden"},
            },
            format="json",
        )
    )
    out["submit"] = _ok(student.submit(attempt_id))

    teacher = auth_client(world.teacher)
    out["grading_pending"] = _ok(teacher.get("/api/v1/grading/pending"))
    answer = StudentAnswer.objects.get(
        attempt_id=attempt_id,
        attempt_question__snapshot_question__source_exam_question_id=eq["open"].id,
    )
    out["grade"] = _ok(
        teacher.patch(
            f"/api/v1/answers/{answer.id}/grade",
            {"points_awarded": "3.50", "teacher_feedback": "Yaxshi"},
            format="json",
        )
    )
    out["attempt_result_student"] = _ok(student.detail(attempt_id))
    out["attempt_staff_detail"] = _ok(teacher.get(f"/api/v1/attempts/{attempt_id}"))
    out["attempt_list_student"] = _ok(student.client.get("/api/v1/attempts"))
    out["results_teacher"] = _ok(teacher.get("/api/v1/results"))
    out["results_summary_teacher"] = _ok(teacher.get("/api/v1/results/summary"))
    out["dashboard_student"] = _ok(student.client.get("/api/v1/student/dashboard"))
    out["dashboard_teacher"] = _ok(teacher.get("/api/v1/teacher/dashboard"))
    out["dashboard_admin"] = _ok(auth_client(admin).get("/api/v1/admin/dashboard"))
    out["assignments_student"] = _ok(student.client.get("/api/v1/exam-assignments"))
    out["questions_summary"] = _ok(teacher.get("/api/v1/questions/summary"))
    out["exams_summary"] = _ok(teacher.get("/api/v1/exams/summary"))
    return out


STEPS = [
    "start",
    "attempt_in_progress",
    "save_answer_choice",
    "save_answer_text",
    "event",
    "submit",
    "grading_pending",
    "grade",
    "attempt_result_student",
    "attempt_staff_detail",
    "attempt_list_student",
    "results_teacher",
    "results_summary_teacher",
    "dashboard_student",
    "dashboard_teacher",
    "dashboard_admin",
    "assignments_student",
    "questions_summary",
    "exams_summary",
]


def test_exam_flow_response_shapes(flow):
    for step in STEPS:
        assert_shape_snapshot(f"golden_{step}", flow[step])


def test_auth_response_shapes(api_client, student):
    login = _ok(
        api_client.post(
            "/api/v1/auth/login",
            {"username_or_email": student.username, "password": DEFAULT_PASSWORD},
            format="json",
        )
    )
    assert_shape_snapshot("golden_auth_login", login)
    refresh = _ok(
        api_client.post(
            "/api/v1/auth/refresh", {"refresh_token": login["refresh_token"]}, format="json"
        )
    )
    assert_shape_snapshot("golden_auth_refresh", refresh)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh['access_token']}")
    assert_shape_snapshot("golden_auth_me", _ok(api_client.get("/api/v1/auth/me")))


def _contains_key(payload, key) -> bool:
    if isinstance(payload, dict):
        return key in payload or any(_contains_key(v, key) for v in payload.values())
    if isinstance(payload, list):
        return any(_contains_key(item, key) for item in payload)
    return False


@pytest.mark.parametrize(
    "mode,released",
    [
        (ResultReviewMode.SCORE_ONLY, False),
        (ResultReviewMode.AFTER_GRADING, False),
        (ResultReviewMode.FULL_REVIEW, False),
    ],
)
def test_student_never_sees_answer_key_unless_released(api, make_world, mode, released):
    """Ma’lumot sizib chiqmasligi: `is_correct` studentga faqat FULL_REVIEW + release da."""
    world = make_world(open_ended=False, result_review_mode=mode, answer_review_released=released)
    student = api(world.student)
    attempt_id = _ok(student.start(world.assignment), 201)["id"]
    in_progress = _ok(student.detail(attempt_id))
    assert not _contains_key(in_progress, "is_correct")
    student.answer(
        attempt_id, world.eq["single"], option_ids=[option_id(world.q["single"], "Right")]
    )
    result = _ok(student.submit(attempt_id))
    assert not _contains_key(result, "is_correct")
    assert not _contains_key(_ok(student.detail(attempt_id)), "is_correct")

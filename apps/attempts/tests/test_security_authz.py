"""Avtorizatsiya (IDOR) regression testlari: barcha muhim endpointlar boshqa kursning ID'lari bilan
begona student, begona teacher va kursdagi oddiy student nomidan chaqiriladi.

Yangi endpoint qo'shilsa — `_requests` ro'yxatiga ham qo'shing.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.tests.factories import (
    EnrollmentFactory,
    GroupStudentFactory,
    ModuleFactory,
    StudyGroupFactory,
)
from apps.attempts.models import StudentAnswer
from apps.attempts.tests.conftest import option_id
from apps.notifications.models import Notification
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db
DENIED = {401, 403, 404, 405}
EVENT_ID = "6f0f4a5e-1111-4a5e-8a5e-111111111111"


@pytest.fixture
def victim(api, make_world):
    world = make_world()
    client = api(world.student)
    attempt_id = client.start(world.assignment).json()["id"]
    single = world.q["single"]
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(single, "Right")])
    client.answer(attempt_id, world.eq["open"], text_answer="SECRET-ESSAY")
    client.submit(attempt_id)
    group = StudyGroupFactory(course=world.course)
    GroupStudentFactory(group=group, student=world.student)
    return {
        "w": world,
        "attempt": attempt_id,
        "group": str(group.id),
        "module": str(ModuleFactory(course=world.course).id),
        "answer": str(StudentAnswer.objects.filter(attempt_id=attempt_id).first().id),
        "note": str(
            Notification.objects.create(recipient=world.student, type="ASSIGNMENT", title="t").id
        ),
    }


def _requests(v):
    w = v["w"]
    c, e, a, q = w.course.id, w.exam.id, w.assignment.id, w.q["single"].id
    s, t, eq = w.student.id, w.teacher.id, w.eq["single"].id
    at, g, m, ans, n = v["attempt"], v["group"], v["module"], v["answer"], v["note"]
    course = f"/api/v1/courses/{c}"
    return [
        ("get", course, None),
        ("patch", course, {"name": "pwn"}),
        ("post", f"{course}/archive", None),
        ("put", f"{course}/status", {"status": "ARCHIVED"}),
        ("get", f"{course}/teachers", None),
        ("post", f"{course}/teachers", {"teacher_id": str(t), "type": "SUPPORT"}),
        ("get", f"{course}/students", None),
        ("post", f"{course}/students", {"student_id": str(s)}),
        ("post", f"{course}/enrollments", {"student_id": str(s)}),
        ("delete", f"{course}/enrollments/{s}", None),
        ("get", f"{course}/modules", None),
        ("post", f"{course}/modules", {"title": "pwn"}),
        ("get", f"{course}/modules/{m}", None),
        ("patch", f"{course}/modules/{m}", {"title": "pwn"}),
        ("delete", f"{course}/modules/{m}", None),
        ("get", f"{course}/groups", None),
        ("get", f"{course}/groups/{g}", None),
        ("patch", f"{course}/groups/{g}", {"name": "pwn"}),
        ("get", f"{course}/groups/{g}/students", None),
        ("post", f"{course}/groups/{g}/students", {"student_id": str(s)}),
        ("get", f"/api/v1/groups/{g}", None),
        ("patch", f"/api/v1/groups/{g}", {"name": "pwn"}),
        ("get", f"/api/v1/groups/{g}/eligible-students", None),
        ("post", f"/api/v1/groups/{g}/students", {"student_id": str(s)}),
        ("delete", f"/api/v1/groups/{g}/students/{s}", None),
        ("get", f"/api/v1/questions/{q}", None),
        ("patch", f"/api/v1/questions/{q}", {"text": "pwn"}),
        ("delete", f"/api/v1/questions/{q}", None),
        (
            "post",
            "/api/v1/questions",
            {"course_id": str(c), "module_id": m, "type": "OPEN_ENDED", "text": "x"},
        ),
        ("get", f"/api/v1/questions/import-template?course_id={c}&module_id={m}", None),
        ("get", f"/api/v1/questions/import-template-json?course_id={c}&module_id={m}", None),
        ("get", f"/api/v1/exams/{e}", None),
        ("patch", f"/api/v1/exams/{e}", {"title": "pwn"}),
        ("post", f"/api/v1/exams/{e}/duplicate", None),
        ("delete", f"/api/v1/exams/{e}", None),
        ("post", "/api/v1/exams", {"course_id": str(c), "title": "x", "passing_score_percent": 5}),
        ("get", f"/api/v1/exam-assignments/{a}", None),
        ("patch", f"/api/v1/exam-assignments/{a}", {"duration_minutes": 999}),
        ("post", f"/api/v1/exam-assignments/{a}/pause", None),
        ("post", f"/api/v1/exam-assignments/{a}/release-answer-review", None),
        ("get", f"/api/v1/exam-assignments/{a}/review-policy", None),
        ("post", f"/api/v1/exam-assignments/{a}/start", None),
        (
            "post",
            "/api/v1/exam-assignments",
            {
                "exam_id": str(e),
                "audience_type": "ALL_COURSE_STUDENTS",
                "start_at": (timezone.now() - timedelta(hours=1)).isoformat(),
                "end_at": (timezone.now() + timedelta(days=1)).isoformat(),
                "duration_minutes": 30,
                "max_attempts": 2,
            },
        ),
        ("get", f"/api/v1/attempts/{at}", None),
        ("put", f"/api/v1/attempts/{at}/answers/{eq}", {"option_ids": [], "revision": 99}),
        ("post", f"/api/v1/attempts/{at}/submit", None),
        (
            "post",
            f"/api/v1/attempts/{at}/events",
            {"event_id": EVENT_ID, "type": "COPY", "client_at": "2026-01-01T00:00:00Z"},
        ),
        ("patch", f"/api/v1/answers/{ans}/grade", {"points_awarded": 4}),
        ("get", f"/api/v1/notifications/{n}", None),
        ("post", f"/api/v1/notifications/{n}/mark-read", None),
        ("get", f"/api/v1/admin/accounts/{s}", None),
        ("get", f"/api/v1/students/{s}", None),
        ("get", f"/api/v1/teachers/{t}", None),
        ("get", "/api/v1/admin/dashboard", None),
    ]


LIST_ENDPOINTS = [
    "/api/v1/courses",
    "/api/v1/groups",
    "/api/v1/questions",
    "/api/v1/exams",
    "/api/v1/exam-assignments",
    "/api/v1/attempts",
    "/api/v1/results",
    "/api/v1/grading/pending",
    "/api/v1/notifications",
    "/api/v1/questions/summary",
    "/api/v1/exams/summary",
    "/api/v1/courses/summary",
    "/api/v1/groups/summary",
    "/api/v1/results/summary",
    "/api/v1/teacher/dashboard",
    "/api/v1/student/dashboard",
    "/api/v1/exam-assignments/summary",
    "/api/v1/notifications/summary",
]


def _secrets(v):
    w = v["w"]
    return {
        "course": str(w.course.id),
        "exam": str(w.exam.id),
        "assignment": str(w.assignment.id),
        "attempt": v["attempt"],
        "student_email": w.student.email,
        "essay": "SECRET-ESSAY",
        "question": str(w.q["single"].id),
    }


def _probe(client, v, skip=()):
    findings = []
    for method, url, body in _requests(v):
        if any(part in url for part in skip):
            continue
        call = getattr(client, method)
        response = call(url, body, format="json") if body is not None else call(url)
        if response.status_code not in DENIED:
            findings.append(f"{method.upper()} {url} -> {response.status_code}")
    for url in LIST_ENDPOINTS:
        response = client.get(url)
        if response.status_code in DENIED:
            continue
        text = response.content.decode()
        leaked = [key for key, value in _secrets(v).items() if value in text]
        if leaked:
            findings.append(f"LIST {url} leaks {leaked}")
    return findings


def test_outsider_student_cannot_access_another_course(auth_client, victim):
    assert _probe(auth_client(StudentFactory()), victim) == []


def test_outsider_teacher_cannot_access_another_course(auth_client, victim):
    assert _probe(auth_client(TeacherFactory()), victim) == []


def test_enrolled_student_cannot_use_staff_endpoints(auth_client, victim):
    """O'z kursidagi student faqat o'ziga tegishli narsalarni o'qiy oladi."""
    w = victim["w"]
    own_reads = (
        f"/attempts/{victim['attempt']}",
        "/start",
        f"/notifications/{victim['note']}",
        f"/exam-assignments/{w.assignment.id}",
    )
    findings = _probe(auth_client(w.student), victim, skip=own_reads)
    course = f"/api/v1/courses/{w.course.id}"
    allowed = {
        f"GET {course} -> 200",
        f"GET {course}/modules -> 200",
        f"GET {course}/modules/{victim['module']} -> 200",
        f"GET /api/v1/groups/{victim['group']} -> 200",
    }
    unexpected = [f for f in findings if f not in allowed and not f.startswith("LIST ")]
    assert unexpected == []


def test_student_never_sees_classmates_personal_data(auth_client, victim):
    w = victim["w"]
    mate = StudentFactory()
    EnrollmentFactory(course=w.course, student=mate)
    GroupStudentFactory(group_id=victim["group"], student=mate)
    client = auth_client(w.student)
    for url in [
        f"/api/v1/groups/{victim['group']}",
        "/api/v1/groups",
        f"/api/v1/courses/{w.course.id}",
    ]:
        body = client.get(url).content.decode()
        assert mate.email not in body and mate.full_name not in body, url


def test_exam_content_hidden_before_start(auth_client, make_world):
    world = make_world(
        start_at=timezone.now() + timedelta(days=1), end_at=timezone.now() + timedelta(days=2)
    )
    client = auth_client(world.student)
    texts = [question.text for question in world.q.values()]
    for url in [
        f"/api/v1/exam-assignments/{world.assignment.id}",
        "/api/v1/exam-assignments",
        "/api/v1/student/dashboard",
        f"/api/v1/courses/{world.course.id}/modules?with_questions=true",
    ]:
        body = client.get(url).content.decode()
        assert "is_correct" not in body, url
        assert not [text for text in texts if text in body], url
    assert client.get(f"/api/v1/exams/{world.exam.id}").status_code in DENIED
    assert client.post(f"/api/v1/exam-assignments/{world.assignment.id}/start").status_code == 400

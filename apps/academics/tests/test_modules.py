import pytest

from apps.academics.choices import CourseStatus, EnrollmentStatus, ModuleStatus
from apps.academics.models import Module
from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    ModuleFactory,
)
from apps.exams.tests.factories import ExamModuleFactory
from apps.questions.choices import QuestionStatus
from apps.questions.tests.factories import QuestionFactory

pytestmark = pytest.mark.django_db


def url(course, module=None):
    base = f"/api/v1/courses/{course.id}/modules"
    return f"{base}/{module.id}" if module else base


@pytest.fixture
def course(teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    return course


# ---------------------------- create / update ----------------------------
def test_teacher_creates_modules_with_auto_position(auth_client, teacher, course):
    client = auth_client(teacher)
    first = client.post(url(course), {"title": "Basics", "description": "Intro"}, format="json")
    second = client.post(url(course), {"title": "OOP"}, format="json")

    assert first.status_code == 201
    assert first.json()["position"] == 1
    assert first.json()["question_count"] == 0
    assert first.json()["status"] == "ACTIVE"
    assert second.json()["position"] == 2


def test_admin_can_create_module_with_explicit_position(auth_client, admin):
    course = CourseFactory()
    response = auth_client(admin).post(url(course), {"title": "X", "position": 7}, format="json")
    assert response.status_code == 201
    assert response.json()["position"] == 7


def test_any_assigned_teacher_can_edit_shared_module(auth_client, teacher, course):
    other = CourseTeacherFactory(course=course).teacher
    module = ModuleFactory(course=course, title="Old")
    response = auth_client(other).patch(url(course, module), {"title": "New"}, format="json")
    assert response.status_code == 200
    assert response.json()["title"] == "New"
    module.refresh_from_db()
    assert module.title == "New"


def test_module_validation(auth_client, admin):
    course = CourseFactory()
    client = auth_client(admin)
    assert client.post(url(course), {}, format="json").status_code == 422
    bad = client.post(url(course), {"title": "X", "position": 0}, format="json")
    assert bad.status_code == 422
    assert "position" in bad.json()["errors"]


# ---------------------------- permissions ----------------------------
def test_unassigned_teacher_gets_404(auth_client, teacher):
    course = CourseFactory()
    client = auth_client(teacher)
    assert client.get(url(course)).status_code == 404
    assert client.post(url(course), {"title": "X"}, format="json").status_code == 404


def test_enrolled_student_reads_but_cannot_write(auth_client, student, course):
    EnrollmentFactory(course=course, student=student)
    module = ModuleFactory(course=course)
    client = auth_client(student)

    assert client.get(url(course)).status_code == 200
    assert client.get(url(course, module)).status_code == 200
    assert client.post(url(course), {"title": "X"}, format="json").status_code == 403
    assert client.patch(url(course, module), {"title": "Y"}, format="json").status_code == 403
    assert client.delete(url(course, module)).status_code == 403


def test_removed_or_unenrolled_student_gets_404(auth_client, student):
    course = CourseFactory()
    assert auth_client(student).get(url(course)).status_code == 404
    EnrollmentFactory(course=course, student=student, status=EnrollmentStatus.REMOVED)
    assert auth_client(student).get(url(course)).status_code == 404


def test_module_of_another_course_is_not_reachable_via_this_course(auth_client, admin):
    course = CourseFactory()
    foreign = ModuleFactory()
    assert auth_client(admin).get(url(course, foreign)).status_code == 404


def test_anonymous_gets_401(api_client, course):
    assert api_client.get(url(course)).status_code == 401


# ---------------------------- list ----------------------------
def test_list_is_ordered_by_position_and_hides_archived(auth_client, admin):
    course = CourseFactory()
    ModuleFactory(course=course, title="Third", position=3)
    ModuleFactory(course=course, title="First", position=1)
    ModuleFactory(course=course, title="Hidden", position=2, status=ModuleStatus.ARCHIVED)
    client = auth_client(admin)

    titles = [m["title"] for m in client.get(url(course)).json()["data"]]
    assert titles == ["First", "Third"]

    archived = client.get(url(course), {"status": "ARCHIVED"}).json()["data"]
    assert [m["title"] for m in archived] == ["Hidden"]


def test_question_count_counts_only_active_questions(auth_client, admin):
    course = CourseFactory()
    module = ModuleFactory(course=course)
    QuestionFactory.create_batch(2, course=course, module=module)
    QuestionFactory(course=course, module=module, status=QuestionStatus.ARCHIVED)
    QuestionFactory(course=course)  # boshqa modul

    body = auth_client(admin).get(url(course, module)).json()
    assert body["question_count"] == 2


def test_with_questions_preview_is_limited_and_hidden_from_students(
    auth_client, teacher, student, course
):
    module = ModuleFactory(course=course)
    QuestionFactory.create_batch(7, course=course, module=module)
    EnrollmentFactory(course=course, student=student)

    data = auth_client(teacher).get(url(course), {"with_questions": "true"}).json()["data"]
    assert len(data[0]["questions"]) == 5
    assert set(data[0]["questions"][0]) == {"id", "type", "text", "default_points"}
    assert data[0]["question_count"] == 7

    student_data = auth_client(student).get(url(course), {"with_questions": "true"}).json()["data"]
    assert "questions" not in student_data[0]

    plain = auth_client(teacher).get(url(course)).json()["data"]
    assert "questions" not in plain[0]


# ---------------------------- delete / archive ----------------------------
def test_delete_unused_module_removes_it(auth_client, admin):
    course = CourseFactory()
    module = ModuleFactory(course=course)
    response = auth_client(admin).delete(url(course, module))
    assert response.status_code == 204
    assert not Module.objects.filter(pk=module.pk).exists()


def test_delete_module_with_questions_archives_it(auth_client, admin):
    course = CourseFactory()
    module = ModuleFactory(course=course)
    QuestionFactory(course=course, module=module)
    response = auth_client(admin).delete(url(course, module))
    assert response.status_code == 200
    assert response.json() == {"archived": True}
    module.refresh_from_db()
    assert module.status == ModuleStatus.ARCHIVED


def test_delete_module_used_by_exam_archives_it(auth_client, admin):
    course = CourseFactory()
    exam_module = ExamModuleFactory(exam__course=course, module__course=course)
    response = auth_client(admin).delete(url(course, exam_module.module))
    assert response.status_code == 200
    assert response.json() == {"archived": True}


def test_archived_course_blocks_module_changes(auth_client, admin):
    course = CourseFactory(status=CourseStatus.ARCHIVED)
    module = ModuleFactory(course=course)
    client = auth_client(admin)

    assert client.post(url(course), {"title": "X"}, format="json").status_code == 400
    assert client.patch(url(course, module), {"title": "Y"}, format="json").status_code == 400
    assert client.delete(url(course, module)).status_code == 400
    assert client.get(url(course)).status_code == 200

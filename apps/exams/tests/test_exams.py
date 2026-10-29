from decimal import Decimal

import pytest

from apps.academics.choices import CourseStatus, ModuleStatus
from apps.academics.tests.factories import CourseFactory, CourseTeacherFactory, ModuleFactory
from apps.assignments.choices import AssignmentStatus
from apps.assignments.tests.factories import AssignmentFactory
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam, ExamModule, ExamQuestion
from apps.exams.tests.factories import ExamFactory, ExamModuleFactory, ExamQuestionFactory
from apps.questions.choices import QuestionStatus
from apps.questions.models import Question
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import TeacherFactory

pytestmark = pytest.mark.django_db

EXAMS = "/api/v1/exams"


@pytest.fixture
def ctx(teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    module_a = ModuleFactory(course=course, title="A")
    module_b = ModuleFactory(course=course, title="B")
    return {
        "teacher": teacher,
        "course": course,
        "module_a": module_a,
        "module_b": module_b,
        "q1": QuestionFactory(course=course, module=module_a, default_points=2),
        "q2": QuestionFactory(course=course, module=module_a, default_points=3),
        "q3": QuestionFactory(course=course, module=module_b, default_points=1),
    }


def payload(ctx, **overrides):
    data = {
        "course_id": str(ctx["course"].id),
        "title": "JavaScript Module 1 Exam",
        "description": "Basics",
        "passing_score_percent": 70,
        "module_ids": [str(ctx["module_a"].id), str(ctx["module_b"].id)],
        "questions": [
            {"question_id": str(ctx["q1"].id), "points": 5},
            {"question_id": str(ctx["q2"].id)},
            {"question_id": str(ctx["q3"].id)},
        ],
    }
    data.update(overrides)
    return data


def create(client, ctx, **overrides):
    return client.post(EXAMS, payload(ctx, **overrides), format="json")


def make_exam(ctx, **kwargs):
    """3 savolli, 2 modulli exam (ExamQuestion lar bilan)."""
    exam = ExamFactory(course=ctx["course"], created_by=ctx["teacher"], **kwargs)
    ExamModule.objects.create(exam=exam, module=ctx["module_a"])
    ExamModule.objects.create(exam=exam, module=ctx["module_b"])
    for position, key in enumerate(("q1", "q2", "q3"), start=1):
        ExamQuestion.objects.create(
            exam=exam, question=ctx[key], points=ctx[key].default_points, position=position
        )
    return exam


# ---------------------------- create ----------------------------
def test_create_exam_with_modules_and_questions(auth_client, ctx):
    response = create(auth_client(ctx["teacher"]), ctx)
    assert response.status_code == 201, response.json()
    body = response.json()

    assert body["status"] == "DRAFT"
    assert body["title"] == "JavaScript Module 1 Exam"
    assert body["passing_score_percent"] == 70
    assert body["questions_count"] == 3
    assert body["total_points"] == 9  # 5 (override) + 3 + 1
    assert body["is_locked"] is False
    assert body["created_by"]["id"] == str(ctx["teacher"].id)
    assert body["course"]["id"] == str(ctx["course"].id)
    assert [m["title"] for m in body["modules"]] == ["A", "B"]

    questions = body["questions"]
    assert [q["position"] for q in questions] == [1, 2, 3]
    assert [q["points"] for q in questions] == [5, 3, 1]
    assert questions[0]["question"]["id"] == str(ctx["q1"].id)
    assert "is_correct" in questions[0]["question"]["options"][0]  # teacher view


def test_create_stores_exam_question_ids_distinct_from_question_ids(auth_client, ctx):
    body = create(auth_client(ctx["teacher"]), ctx).json()
    exam_question = ExamQuestion.objects.get(exam_id=body["id"], question=ctx["q1"])
    assert body["questions"][0]["id"] == str(exam_question.id)
    assert body["questions"][0]["id"] != str(ctx["q1"].id)


def test_create_with_explicit_positions(auth_client, ctx):
    questions = [
        {"question_id": str(ctx["q1"].id), "position": 3},
        {"question_id": str(ctx["q2"].id), "position": 1},
        {"question_id": str(ctx["q3"].id), "position": 2},
    ]
    body = create(auth_client(ctx["teacher"]), ctx, questions=questions).json()
    assert [q["question"]["id"] for q in body["questions"]] == [
        str(ctx["q2"].id),
        str(ctx["q3"].id),
        str(ctx["q1"].id),
    ]


def test_create_rejects_mixed_or_duplicate_positions(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    mixed = [
        {"question_id": str(ctx["q1"].id), "position": 1},
        {"question_id": str(ctx["q2"].id)},
    ]
    assert create(client, ctx, questions=mixed).status_code == 400
    duplicate = [
        {"question_id": str(ctx["q1"].id), "position": 1},
        {"question_id": str(ctx["q2"].id), "position": 1},
    ]
    assert create(client, ctx, questions=duplicate).status_code == 400


def test_create_empty_draft_is_allowed(auth_client, ctx):
    body = create(auth_client(ctx["teacher"]), ctx, module_ids=[], questions=[]).json()
    assert body["questions_count"] == 0
    assert body["total_points"] == 0


def test_ready_exam_requires_questions(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    assert create(client, ctx, status="READY", questions=[]).status_code == 400
    ok = create(client, ctx, status="READY")
    assert ok.status_code == 201
    assert ok.json()["status"] == "READY"


@pytest.mark.parametrize("value", [-1, 100.01, 101, "abc"])
def test_passing_score_must_be_between_0_and_100(auth_client, ctx, value):
    response = create(auth_client(ctx["teacher"]), ctx, passing_score_percent=value)
    assert response.status_code == 422
    assert "passing_score_percent" in response.json()["errors"]


def test_passing_score_boundaries_are_accepted(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    assert create(client, ctx, passing_score_percent=0).status_code == 201
    assert create(client, ctx, passing_score_percent=100).status_code == 201


def test_create_requires_basic_fields_and_valid_status(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    assert client.post(EXAMS, {}, format="json").status_code == 422
    assert create(client, ctx, status="ARCHIVED").status_code == 422
    assert create(client, ctx, title="").status_code == 422


def test_create_rejects_question_outside_selected_modules(auth_client, ctx):
    response = create(auth_client(ctx["teacher"]), ctx, module_ids=[str(ctx["module_a"].id)])
    assert response.status_code == 400  # q3 module B da
    assert "modullarga" in response.json()["message"]


def test_create_rejects_foreign_course_question_and_module(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    foreign_question = QuestionFactory()
    questions = [{"question_id": str(foreign_question.id)}]
    assert create(client, ctx, questions=questions).status_code == 400

    foreign_module = ModuleFactory()
    response = create(client, ctx, module_ids=[str(foreign_module.id)], questions=[])
    assert response.status_code == 400


def test_create_rejects_archived_question_and_module(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    ctx["q3"].status = QuestionStatus.ARCHIVED
    ctx["q3"].save()
    assert create(client, ctx).status_code == 400

    ctx["q3"].status = QuestionStatus.ACTIVE
    ctx["q3"].save()
    ctx["module_b"].status = ModuleStatus.ARCHIVED
    ctx["module_b"].save()
    assert create(client, ctx).status_code == 400


def test_create_rejects_duplicates(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    dup_questions = [{"question_id": str(ctx["q1"].id)}, {"question_id": str(ctx["q1"].id)}]
    assert create(client, ctx, questions=dup_questions).status_code == 400
    dup_modules = [str(ctx["module_a"].id), str(ctx["module_a"].id)]
    assert create(client, ctx, module_ids=dup_modules, questions=[]).status_code == 400


def test_create_with_unknown_ids_returns_422(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    ghost = "00000000-0000-4000-8000-000000000000"
    assert create(client, ctx, questions=[{"question_id": ghost}]).status_code == 422
    assert create(client, ctx, module_ids=[ghost], questions=[]).status_code == 422
    assert create(client, ctx, course_id=ghost).status_code == 422


def test_create_access_rules(auth_client, admin, student, ctx):
    assert create(auth_client(TeacherFactory()), ctx).status_code == 403
    assert create(auth_client(student), ctx).status_code == 403
    assert create(auth_client(admin), ctx).status_code == 201

    ctx["course"].status = CourseStatus.ARCHIVED
    ctx["course"].save()
    assert create(auth_client(ctx["teacher"]), ctx).status_code == 400


def test_anonymous_cannot_access_exams(api_client):
    assert api_client.get(EXAMS).status_code == 401


# ---------------------------- list / retrieve ----------------------------
def test_list_has_totals_and_hides_archived(auth_client, ctx):
    exam = make_exam(ctx)
    ExamFactory(course=ctx["course"], status=ExamStatus.ARCHIVED)
    client = auth_client(ctx["teacher"])

    data = client.get(EXAMS).json()["data"]
    assert [e["id"] for e in data] == [str(exam.id)]
    assert data[0]["questions_count"] == 3
    assert data[0]["modules_count"] == 2
    assert data[0]["total_points"] == 6  # 2 + 3 + 1
    assert data[0]["uses_count"] == 0
    assert "questions" not in data[0]

    archived = client.get(EXAMS, {"status": "ARCHIVED"}).json()["data"]
    assert len(archived) == 1


def test_exam_list_counts_assignment_uses_without_distorting_totals(auth_client, ctx):
    exam = make_exam(ctx, status=ExamStatus.READY)
    AssignmentFactory.create_batch(2, exam=exam, ensure_question=False)

    body = auth_client(ctx["teacher"]).get(EXAMS).json()["data"][0]

    assert body["modules_count"] == 2
    assert body["questions_count"] == 3
    assert body["total_points"] == 6
    assert body["uses_count"] == 2


def test_exam_library_summary_is_role_scoped(auth_client, admin, student, ctx):
    ExamFactory(course=ctx["course"], created_by=ctx["teacher"], status=ExamStatus.DRAFT)
    ExamFactory(course=ctx["course"], created_by=ctx["teacher"], status=ExamStatus.READY)
    ExamFactory(course=ctx["course"], created_by=ctx["teacher"], status=ExamStatus.ARCHIVED)
    ExamFactory()  # teacherga ko‘rinmaydigan boshqa kurs imtihoni

    teacher_summary = auth_client(ctx["teacher"]).get(f"{EXAMS}/summary")
    assert teacher_summary.status_code == 200
    assert teacher_summary.json() == {
        "total_exams": 3,
        "draft_exams": 1,
        "ready_exams": 1,
        "archived_exams": 1,
    }

    admin_summary = auth_client(admin).get(f"{EXAMS}/summary")
    assert admin_summary.status_code == 200
    assert admin_summary.json()["total_exams"] == 4
    assert auth_client(student).get(f"{EXAMS}/summary").status_code == 403


def test_teacher_sees_exams_of_assigned_courses_including_colleagues(auth_client, ctx):
    colleague = CourseTeacherFactory(course=ctx["course"], type="SUPPORT").teacher
    theirs = ExamFactory(course=ctx["course"], created_by=colleague)
    foreign = ExamFactory()
    client = auth_client(ctx["teacher"])

    assert [e["id"] for e in client.get(EXAMS).json()["data"]] == [str(theirs.id)]
    assert client.get(f"{EXAMS}/{theirs.id}").status_code == 200
    assert client.get(f"{EXAMS}/{foreign.id}").status_code == 404


def test_list_filters(auth_client, admin, ctx):
    other = TeacherFactory()
    mine = ExamFactory(course=ctx["course"], created_by=ctx["teacher"], title="Alpha exam")
    theirs = ExamFactory(
        course=ctx["course"], created_by=other, title="Beta", status=ExamStatus.READY
    )
    elsewhere = ExamFactory(title="Gamma")
    client = auth_client(admin)

    def ids(query=""):
        return {e["id"] for e in client.get(f"{EXAMS}?{query}").json()["data"]}

    assert ids(f"course_id={ctx['course'].id}") == {str(mine.id), str(theirs.id)}
    assert ids("status=READY") == {str(theirs.id)}
    assert ids("search=alpha") == {str(mine.id)}
    assert ids(f"creator_ids={other.id}") == {str(theirs.id)}
    both = f"creator_ids={other.id}&creator_ids={ctx['teacher'].id}"
    assert ids(both) == {str(mine.id), str(theirs.id)}
    assert str(elsewhere.id) not in ids(f"creator_ids={other.id},{ctx['teacher'].id}")


def test_student_cannot_list_or_read_exams(auth_client, student, ctx):
    exam = make_exam(ctx)
    client = auth_client(student)
    assert client.get(EXAMS).status_code == 403
    assert client.get(f"{EXAMS}/{exam.id}").status_code == 403


def test_detail_query_count_does_not_grow_with_questions(
    auth_client, ctx, django_assert_max_num_queries
):
    exam = make_exam(ctx)
    for _ in range(10):
        ExamQuestionFactory(exam=exam, question__module=ctx["module_a"])
    client = auth_client(ctx["teacher"])
    with django_assert_max_num_queries(12):
        assert client.get(f"{EXAMS}/{exam.id}").status_code == 200


# ---------------------------- update ----------------------------
def test_update_scalar_fields_only(auth_client, ctx):
    exam = make_exam(ctx)
    response = auth_client(ctx["teacher"]).patch(
        f"{EXAMS}/{exam.id}",
        {"title": "Renamed", "description": "New", "passing_score_percent": 55.5},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["description"], body["passing_score_percent"]) == (
        "Renamed",
        "New",
        55.5,
    )
    assert body["questions_count"] == 3  # kontent tegilmagan


def test_update_questions_keeps_ids_of_retained_ones(auth_client, ctx):
    exam = make_exam(ctx)
    keep_id = ExamQuestion.objects.get(exam=exam, question=ctx["q1"]).id
    dropped_id = ExamQuestion.objects.get(exam=exam, question=ctx["q2"]).id
    new_question = QuestionFactory(course=ctx["course"], module=ctx["module_b"], default_points=4)

    response = auth_client(ctx["teacher"]).patch(
        f"{EXAMS}/{exam.id}",
        {
            "questions": [
                {"question_id": str(ctx["q3"].id), "position": 1},
                {"question_id": str(ctx["q1"].id), "position": 2, "points": 9},
                {"question_id": str(new_question.id), "position": 3},
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    body = response.json()

    assert [q["question"]["id"] for q in body["questions"]] == [
        str(ctx["q3"].id),
        str(ctx["q1"].id),
        str(new_question.id),
    ]
    by_question = {q["question"]["id"]: q for q in body["questions"]}
    assert by_question[str(ctx["q1"].id)]["id"] == str(keep_id)  # ExamQuestion ID saqlandi
    assert by_question[str(ctx["q1"].id)]["points"] == 9
    assert by_question[str(ctx["q3"].id)]["points"] == 1  # mavjud points saqlandi
    assert by_question[str(new_question.id)]["points"] == 4  # default_points
    assert not ExamQuestion.objects.filter(pk=dropped_id).exists()
    assert body["total_points"] == 14


def test_update_modules_replaces_set_and_validates_questions(auth_client, ctx):
    exam = make_exam(ctx)
    client = auth_client(ctx["teacher"])
    url = f"{EXAMS}/{exam.id}"

    # B modulini olib tashlash — q3 hali exam da bo‘lgani uchun rad etiladi.
    rejected = client.patch(url, {"module_ids": [str(ctx["module_a"].id)]}, format="json")
    assert rejected.status_code == 400

    ok = client.patch(
        url,
        {
            "module_ids": [str(ctx["module_a"].id)],
            "questions": [{"question_id": str(ctx["q1"].id)}],
        },
        format="json",
    )
    assert ok.status_code == 200
    assert [m["title"] for m in ok.json()["modules"]] == ["A"]
    assert not ExamModule.objects.filter(exam=exam, module=ctx["module_b"]).exists()


def test_update_status_transitions(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    empty = ExamFactory(course=ctx["course"], created_by=ctx["teacher"])
    assert (
        client.patch(f"{EXAMS}/{empty.id}", {"status": "READY"}, format="json").status_code == 400
    )

    exam = make_exam(ctx)
    ready = client.patch(f"{EXAMS}/{exam.id}", {"status": "READY"}, format="json")
    assert ready.status_code == 200 and ready.json()["status"] == "READY"
    back = client.patch(f"{EXAMS}/{exam.id}", {"status": "DRAFT"}, format="json")
    assert back.status_code == 200 and back.json()["status"] == "DRAFT"
    assert (
        client.patch(f"{EXAMS}/{exam.id}", {"status": "ARCHIVED"}, format="json").status_code == 422
    )


def test_update_keeps_working_after_a_used_question_gets_archived(auth_client, ctx):
    exam = make_exam(ctx)
    ctx["q1"].status = QuestionStatus.ARCHIVED
    ctx["q1"].save()
    client = auth_client(ctx["teacher"])
    url = f"{EXAMS}/{exam.id}"

    # Mavjud (keyin arxivlangan) savol bilan qayta saqlash mumkin.
    same = [{"question_id": str(ctx[k].id)} for k in ("q1", "q2", "q3")]
    assert client.patch(url, {"questions": same}, format="json").status_code == 200
    # Lekin yangi arxivlangan savolni qo‘shib bo‘lmaydi.
    archived_new = QuestionFactory(
        course=ctx["course"], module=ctx["module_a"], status=QuestionStatus.ARCHIVED
    )
    more = [*same, {"question_id": str(archived_new.id)}]
    assert client.patch(url, {"questions": more}, format="json").status_code == 400


def test_only_author_or_admin_can_modify(auth_client, admin, ctx):
    exam = make_exam(ctx)
    colleague = CourseTeacherFactory(course=ctx["course"], type="SUPPORT").teacher
    client = auth_client(colleague)
    url = f"{EXAMS}/{exam.id}"

    assert client.get(url).status_code == 200
    assert client.patch(url, {"title": "Hijack"}, format="json").status_code == 403
    assert client.delete(url).status_code == 403
    assert client.post(f"{url}/archive").status_code == 403
    assert auth_client(admin).patch(url, {"title": "By admin"}, format="json").status_code == 200


def test_archived_exam_cannot_be_edited(auth_client, ctx):
    exam = ExamFactory(course=ctx["course"], created_by=ctx["teacher"], status=ExamStatus.ARCHIVED)
    response = auth_client(ctx["teacher"]).patch(
        f"{EXAMS}/{exam.id}", {"title": "X"}, format="json"
    )
    assert response.status_code == 400


def test_assigned_exam_template_stays_editable_because_snapshot_is_immutable(auth_client, ctx):
    exam = make_exam(ctx, status=ExamStatus.READY)
    assignment = AssignmentFactory(
        exam=exam, status=AssignmentStatus.PUBLISHED, ensure_question=False
    )
    client = auth_client(ctx["teacher"])
    url = f"{EXAMS}/{exam.id}"

    assert client.get(url).json()["is_locked"] is False
    assert client.patch(url, {"passing_score_percent": 10}, format="json").status_code == 200
    assert client.patch(url, {"title": "Typo fixed"}, format="json").status_code == 200
    exam.refresh_from_db()
    assert exam.passing_score_percent == Decimal("10")
    assert exam.exam_questions.count() == 3
    assert assignment.snapshot.passing_score_percent == Decimal("70")


# ---------------------------- duplicate ----------------------------
def test_duplicate_creates_independent_draft_owned_by_caller(auth_client, ctx):
    exam = make_exam(ctx, status=ExamStatus.READY)
    colleague = CourseTeacherFactory(course=ctx["course"], type="SUPPORT").teacher

    response = auth_client(colleague).post(f"{EXAMS}/{exam.id}/duplicate")
    assert response.status_code == 201
    body = response.json()

    assert body["id"] != str(exam.id)
    assert body["title"] == f"{exam.title} (nusxa)"
    assert body["status"] == "DRAFT"
    assert body["created_by"]["id"] == str(colleague.id)
    assert body["skipped_question_ids"] == []
    assert [q["points"] for q in body["questions"]] == [2, 3, 1]
    assert [m["title"] for m in body["modules"]] == ["A", "B"]
    # ExamQuestion lar nusxalanadi, ID lar alohida.
    original_ids = set(exam.exam_questions.values_list("id", flat=True))
    assert not original_ids & {q["id"] for q in body["questions"]}
    assert exam.exam_questions.count() == 3


def test_duplicate_skips_archived_questions_and_reports_them(auth_client, ctx):
    exam = make_exam(ctx)
    ctx["q2"].status = QuestionStatus.ARCHIVED
    ctx["q2"].save()
    body = auth_client(ctx["teacher"]).post(f"{EXAMS}/{exam.id}/duplicate").json()
    assert body["skipped_question_ids"] == [str(ctx["q2"].id)]
    assert body["questions_count"] == 2


def test_duplicate_access_rules(auth_client, student, ctx):
    exam = make_exam(ctx)
    assert auth_client(student).post(f"{EXAMS}/{exam.id}/duplicate").status_code == 403
    assert auth_client(TeacherFactory()).post(f"{EXAMS}/{exam.id}/duplicate").status_code == 404


# ---------------------------- delete / archive ----------------------------
def test_delete_unpublished_exam_removes_it_and_frees_questions(auth_client, ctx):
    exam = make_exam(ctx)
    ctx["q1"].created_by = ctx["teacher"]
    ctx["q1"].save()
    client = auth_client(ctx["teacher"])

    assert client.delete(f"{EXAMS}/{exam.id}").status_code == 204
    assert not Exam.objects.filter(pk=exam.pk).exists()
    assert not ExamQuestion.objects.filter(exam_id=exam.pk).exists()
    # Savol endi hech qayerda ishlatilmaydi -> o‘chirib bo‘ladi.
    assert client.delete(f"/api/v1/questions/{ctx['q1'].id}").status_code == 204
    assert not Question.objects.filter(pk=ctx["q1"].pk).exists()


def test_draft_assignment_does_not_lock_exam_content(auth_client, ctx):
    exam = make_exam(ctx, status=ExamStatus.READY)
    AssignmentFactory(exam=exam, status=AssignmentStatus.DRAFT, ensure_question=False)
    client = auth_client(ctx["teacher"])
    assert client.get(f"{EXAMS}/{exam.id}").json()["is_locked"] is False
    response = client.patch(f"{EXAMS}/{exam.id}", {"passing_score_percent": 50}, format="json")
    assert response.status_code == 200


def test_delete_exam_with_assignments_archives_it(auth_client, ctx):
    exam = make_exam(ctx)
    AssignmentFactory(exam=exam, status=AssignmentStatus.DRAFT, ensure_question=False)
    response = auth_client(ctx["teacher"]).delete(f"{EXAMS}/{exam.id}")
    assert response.status_code == 200
    assert response.json() == {"archived": True}
    exam.refresh_from_db()
    assert exam.status == ExamStatus.ARCHIVED


def test_archive_endpoint(auth_client, ctx):
    exam = make_exam(ctx)
    client = auth_client(ctx["teacher"])
    for _ in range(2):  # idempotent
        response = client.post(f"{EXAMS}/{exam.id}/archive")
        assert response.status_code == 200
        assert response.json()["status"] == "ARCHIVED"


def test_exam_and_module_in_use_cannot_be_hard_deleted_via_db(ctx):
    """DB darajasidagi himoya (PROTECT): service ni chetlab o‘tib bo‘lmaydi."""
    from django.db.models import ProtectedError

    exam = make_exam(ctx)
    with pytest.raises(ProtectedError):
        ctx["q1"].delete()
    with pytest.raises(ProtectedError):
        ctx["module_a"].delete()
    assert exam.exam_questions.count() == 3


def test_course_detail_counts_new_resources(auth_client, admin, ctx):
    make_exam(ctx)
    ExamFactory(course=ctx["course"], status=ExamStatus.ARCHIVED)
    ExamModuleFactory(exam__course=ctx["course"], module__course=ctx["course"])
    ModuleFactory(course=ctx["course"], status=ModuleStatus.ARCHIVED)

    body = auth_client(admin).get(f"/api/v1/courses/{ctx['course'].id}").json()
    assert body["exams_count"] == 2  # arxivlanmaganlar
    assert body["modules_count"] == 3  # A, B + exam_module fabrikasi (arxivlangani sanalmaydi)
    assert body["questions_count"] == 3
    assert body["groups_count"] == 0

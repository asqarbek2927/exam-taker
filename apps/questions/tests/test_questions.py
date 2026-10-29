from decimal import Decimal

import pytest

from apps.academics.choices import CourseStatus, ModuleStatus
from apps.academics.tests.factories import CourseFactory, CourseTeacherFactory, ModuleFactory
from apps.assignments.choices import AssignmentStatus
from apps.assignments.tests.factories import AssignmentFactory
from apps.exams.tests.factories import ExamQuestionFactory
from apps.questions.choices import QuestionStatus, QuestionType
from apps.questions.models import Question, QuestionOption
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import TeacherFactory

pytestmark = pytest.mark.django_db

QUESTIONS = "/api/v1/questions"

TWO_OPTIONS = [
    {"text": "Cannot be reassigned", "is_correct": True},
    {"text": "Can be reassigned", "is_correct": False},
]


@pytest.fixture
def ctx(teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    return {"course": course, "module": ModuleFactory(course=course), "teacher": teacher}


def payload(ctx, **overrides):
    data = {
        "course_id": str(ctx["course"].id),
        "module_id": str(ctx["module"].id),
        "type": "SINGLE_CHOICE",
        "text": "What is const?",
        "options": TWO_OPTIONS,
    }
    data.update(overrides)
    return data


# ---------------------------- create ----------------------------
@pytest.mark.parametrize(
    ("question_type", "options", "expected_points"),
    [
        ("SINGLE_CHOICE", TWO_OPTIONS, 2),
        (
            "MULTIPLE_CHOICE",
            [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": True}],
            3,
        ),
        (
            "TRUE_FALSE",
            [{"text": "True", "is_correct": False}, {"text": "False", "is_correct": True}],
            1,
        ),
        ("OPEN_ENDED", [], 5),
    ],
)
def test_create_each_type_uses_default_points(
    auth_client, ctx, question_type, options, expected_points
):
    response = auth_client(ctx["teacher"]).post(
        QUESTIONS, payload(ctx, type=question_type, options=options), format="json"
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["type"] == question_type
    assert body["default_points"] == expected_points
    assert body["status"] == "ACTIVE"
    assert [o["position"] for o in body["options"]] == list(range(1, len(options) + 1))
    assert [o["is_correct"] for o in body["options"]] == [o["is_correct"] for o in options]


def test_create_sets_author_and_accepts_explicit_points(auth_client, ctx):
    response = auth_client(ctx["teacher"]).post(
        QUESTIONS, payload(ctx, default_points=4.5), format="json"
    )
    body = response.json()
    assert body["default_points"] == 4.5
    assert body["created_by"]["id"] == str(ctx["teacher"].id)
    assert body["course_id"] == str(ctx["course"].id)


def test_create_without_options_for_choice_question_is_rejected(auth_client, ctx):
    data = payload(ctx)
    del data["options"]
    response = auth_client(ctx["teacher"]).post(QUESTIONS, data, format="json")
    assert response.status_code == 422
    assert "options" in response.json()["errors"]


@pytest.mark.parametrize(
    "options",
    [
        [{"text": "A", "is_correct": True}],
        [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": True}],
        [{"text": "A", "is_correct": False}, {"text": "B", "is_correct": False}],
        [{"text": "A", "is_correct": True}, {"text": "a", "is_correct": False}],
        [{"text": "", "is_correct": True}, {"text": "B", "is_correct": False}],
    ],
)
def test_create_rejects_invalid_single_choice_options(auth_client, ctx, options):
    response = auth_client(ctx["teacher"]).post(
        QUESTIONS, payload(ctx, options=options), format="json"
    )
    assert response.status_code == 422
    assert "options" in response.json()["errors"]
    assert Question.objects.count() == 0


def test_create_rejects_options_for_open_ended(auth_client, ctx):
    response = auth_client(ctx["teacher"]).post(
        QUESTIONS, payload(ctx, type="OPEN_ENDED"), format="json"
    )
    assert response.status_code == 422


def test_create_validation_of_basic_fields(auth_client, ctx):
    client = auth_client(ctx["teacher"])
    assert client.post(QUESTIONS, {}, format="json").status_code == 422
    assert client.post(QUESTIONS, payload(ctx, type="NOPE"), format="json").status_code == 422
    assert client.post(QUESTIONS, payload(ctx, text=""), format="json").status_code == 422
    assert client.post(QUESTIONS, payload(ctx, default_points=0), format="json").status_code == 422
    assert client.post(QUESTIONS, payload(ctx, module_id="bad"), format="json").status_code == 422


def test_create_rejects_module_of_another_course(auth_client, ctx):
    foreign = ModuleFactory()
    response = auth_client(ctx["teacher"]).post(
        QUESTIONS, payload(ctx, module_id=str(foreign.id)), format="json"
    )
    assert response.status_code == 400
    assert "modul" in response.json()["message"]


def test_create_rejects_archived_module(auth_client, ctx):
    ctx["module"].status = ModuleStatus.ARCHIVED
    ctx["module"].save()
    response = auth_client(ctx["teacher"]).post(QUESTIONS, payload(ctx), format="json")
    assert response.status_code == 400


def test_create_rejects_archived_course(auth_client, ctx):
    ctx["course"].status = CourseStatus.ARCHIVED
    ctx["course"].save()
    response = auth_client(ctx["teacher"]).post(QUESTIONS, payload(ctx), format="json")
    assert response.status_code == 400


def test_unassigned_teacher_cannot_create_in_course(auth_client, ctx):
    outsider = TeacherFactory()
    response = auth_client(outsider).post(QUESTIONS, payload(ctx), format="json")
    assert response.status_code == 403
    assert response.json()["message"] == "Siz bu kursga biriktirilmagansiz."


def test_admin_can_create_in_any_course(auth_client, admin, ctx):
    response = auth_client(admin).post(QUESTIONS, payload(ctx), format="json")
    assert response.status_code == 201
    assert response.json()["created_by"]["id"] == str(admin.id)


def test_student_and_anonymous_have_no_access(auth_client, api_client, student, ctx):
    assert auth_client(student).get(QUESTIONS).status_code == 403
    assert auth_client(student).post(QUESTIONS, payload(ctx), format="json").status_code == 403
    assert api_client.get(QUESTIONS).status_code == 401


# ---------------------------- scoping / ownership ----------------------------
def test_teacher_sees_only_questions_of_assigned_courses(auth_client, ctx):
    mine = QuestionFactory(course=ctx["course"], module=ctx["module"])
    foreign = QuestionFactory()
    client = auth_client(ctx["teacher"])

    ids = [q["id"] for q in client.get(QUESTIONS).json()["data"]]
    assert ids == [str(mine.id)]
    assert client.get(f"{QUESTIONS}/{foreign.id}").status_code == 404


def test_other_teacher_can_read_but_not_modify(auth_client, ctx):
    question = QuestionFactory(course=ctx["course"], module=ctx["module"])  # boshqa muallif
    client = auth_client(ctx["teacher"])
    url = f"{QUESTIONS}/{question.id}"

    assert client.get(url).status_code == 200
    forbidden = client.patch(url, {"text": "Hacked"}, format="json")
    assert forbidden.status_code == 403
    assert client.delete(url).status_code == 403
    assert client.post(f"{url}/archive").status_code == 403
    question.refresh_from_db()
    assert question.text != "Hacked"


def test_super_admin_can_modify_any_question(auth_client, admin, ctx):
    question = QuestionFactory(course=ctx["course"], module=ctx["module"])
    response = auth_client(admin).patch(
        f"{QUESTIONS}/{question.id}", {"text": "By admin"}, format="json"
    )
    assert response.status_code == 200


# ---------------------------- update ----------------------------
def test_update_scalar_fields_and_module(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    new_module = ModuleFactory(course=ctx["course"])
    response = auth_client(ctx["teacher"]).patch(
        f"{QUESTIONS}/{question.id}",
        {"text": "  Updated  ", "default_points": 3, "module_id": str(new_module.id)},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Updated"
    assert body["default_points"] == 3
    assert body["module_id"] == str(new_module.id)
    assert len(body["options"]) == 3  # options tegilmagan


def test_update_replaces_options(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    old_ids = set(question.options.values_list("id", flat=True))
    response = auth_client(ctx["teacher"]).patch(
        f"{QUESTIONS}/{question.id}", {"options": TWO_OPTIONS}, format="json"
    )
    assert response.status_code == 200
    assert [o["text"] for o in response.json()["options"]] == [o["text"] for o in TWO_OPTIONS]
    assert not old_ids & set(
        QuestionOption.objects.filter(question=question).values_list("id", flat=True)
    )


def test_changing_type_requires_options(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    client = auth_client(ctx["teacher"])
    url = f"{QUESTIONS}/{question.id}"

    assert client.patch(url, {"type": "OPEN_ENDED"}, format="json").status_code == 422
    changed = client.patch(url, {"type": "OPEN_ENDED", "options": []}, format="json")
    assert changed.status_code == 200
    assert changed.json()["type"] == "OPEN_ENDED"
    assert changed.json()["options"] == []


def test_update_validates_options_against_effective_type(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    response = auth_client(ctx["teacher"]).patch(
        f"{QUESTIONS}/{question.id}",
        {"options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": True}]},
        format="json",
    )
    assert response.status_code == 422  # SINGLE_CHOICE da 2 ta to‘g‘ri


def test_archived_question_cannot_be_edited(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"],
        module=ctx["module"],
        created_by=ctx["teacher"],
        status=QuestionStatus.ARCHIVED,
    )
    response = auth_client(ctx["teacher"]).patch(
        f"{QUESTIONS}/{question.id}", {"text": "New"}, format="json"
    )
    assert response.status_code == 400


def test_question_in_assigned_exam_is_editable_but_snapshot_stays_unchanged(auth_client, ctx):
    locked = QuestionFactory(course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"])
    free = QuestionFactory(course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"])
    exam_question = ExamQuestionFactory(exam__course=ctx["course"], question=locked)
    assignment = AssignmentFactory(exam=exam_question.exam, status=AssignmentStatus.PUBLISHED)
    snapshot_text = assignment.snapshot.questions.get(source_question_id=locked.id).text
    client = auth_client(ctx["teacher"])

    response = client.patch(f"{QUESTIONS}/{locked.id}", {"text": "Changed"}, format="json")
    assert response.status_code == 200
    assert assignment.snapshot.questions.get(source_question_id=locked.id).text == snapshot_text
    assert (
        client.patch(f"{QUESTIONS}/{free.id}", {"text": "Changed"}, format="json").status_code
        == 200
    )


def test_question_in_unpublished_exam_is_editable(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    ExamQuestionFactory(exam__course=ctx["course"], question=question)
    response = auth_client(ctx["teacher"]).patch(
        f"{QUESTIONS}/{question.id}", {"text": "Still editable"}, format="json"
    )
    assert response.status_code == 200


# ---------------------------- delete / archive ----------------------------
def test_delete_unused_question_removes_it(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    response = auth_client(ctx["teacher"]).delete(f"{QUESTIONS}/{question.id}")
    assert response.status_code == 204
    assert not Question.objects.filter(pk=question.pk).exists()
    assert not QuestionOption.objects.filter(question_id=question.pk).exists()


def test_delete_question_used_in_exam_archives_it(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    ExamQuestionFactory(exam__course=ctx["course"], question=question)
    response = auth_client(ctx["teacher"]).delete(f"{QUESTIONS}/{question.id}")
    assert response.status_code == 200
    assert response.json() == {"archived": True}
    question.refresh_from_db()
    assert question.status == QuestionStatus.ARCHIVED


def test_archive_endpoint_is_idempotent(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"], module=ctx["module"], created_by=ctx["teacher"]
    )
    client = auth_client(ctx["teacher"])
    for _ in range(2):
        response = client.post(f"{QUESTIONS}/{question.id}/archive")
        assert response.status_code == 200
        assert response.json()["status"] == "ARCHIVED"


def test_restore_endpoint_is_idempotent_and_validates_parent_state(auth_client, ctx):
    question = QuestionFactory(
        course=ctx["course"],
        module=ctx["module"],
        created_by=ctx["teacher"],
        status=QuestionStatus.ARCHIVED,
    )
    client = auth_client(ctx["teacher"])
    url = f"{QUESTIONS}/{question.id}/restore"

    for _ in range(2):
        response = client.post(url)
        assert response.status_code == 200
        assert response.json()["status"] == "ACTIVE"

    question.status = QuestionStatus.ARCHIVED
    question.save(update_fields=["status"])
    ctx["module"].status = ModuleStatus.ARCHIVED
    ctx["module"].save(update_fields=["status"])
    assert client.post(url).status_code == 400


# ---------------------------- list / filters ----------------------------
def test_list_hides_archived_by_default(auth_client, ctx):
    active = QuestionFactory(course=ctx["course"], module=ctx["module"])
    QuestionFactory(course=ctx["course"], module=ctx["module"], status=QuestionStatus.ARCHIVED)
    client = auth_client(ctx["teacher"])

    assert [q["id"] for q in client.get(QUESTIONS).json()["data"]] == [str(active.id)]
    archived = client.get(QUESTIONS, {"status": "ARCHIVED"}).json()["data"]
    assert len(archived) == 1 and archived[0]["status"] == "ARCHIVED"


def test_question_bank_summary_is_role_scoped(auth_client, admin, ctx):
    common = {"course": ctx["course"], "module": ctx["module"]}
    QuestionFactory(type=QuestionType.SINGLE_CHOICE, **common)
    QuestionFactory(type=QuestionType.MULTIPLE_CHOICE, **common)
    QuestionFactory(type=QuestionType.TRUE_FALSE, **common)
    QuestionFactory(type=QuestionType.OPEN_ENDED, **common)
    QuestionFactory(status=QuestionStatus.ARCHIVED, **common)
    QuestionFactory()

    response = auth_client(ctx["teacher"]).get(f"{QUESTIONS}/summary")
    assert response.status_code == 200
    assert response.json() == {
        "active_questions": 4,
        "choice_questions": 2,
        "open_ended": 1,
        "archived": 1,
    }
    assert auth_client(admin).get(f"{QUESTIONS}/summary").json()["active_questions"] == 5


def test_list_includes_course_and_module_details(auth_client, ctx):
    question = QuestionFactory(course=ctx["course"], module=ctx["module"])
    item = auth_client(ctx["teacher"]).get(QUESTIONS).json()["data"][0]

    assert item["id"] == str(question.id)
    assert item["course"] == {
        "id": str(ctx["course"].id),
        "name": ctx["course"].name,
        "status": ctx["course"].status,
    }
    assert item["module"]["id"] == str(ctx["module"].id)
    assert item["module"]["title"] == ctx["module"].title


def test_list_filters(auth_client, admin, ctx):
    other_module = ModuleFactory(course=ctx["course"])
    q1 = QuestionFactory(course=ctx["course"], module=ctx["module"], text="Alpha question")
    q2 = QuestionFactory(
        course=ctx["course"], module=other_module, type=QuestionType.OPEN_ENDED, text="Beta"
    )
    q3 = QuestionFactory(text="Gamma")  # boshqa kurs
    client = auth_client(admin)

    def ids(**params):
        return {q["id"] for q in client.get(QUESTIONS, params).json()["data"]}

    assert ids(course_id=ctx["course"].id) == {str(q1.id), str(q2.id)}
    assert ids(module_id=other_module.id) == {str(q2.id)}
    assert ids(type="OPEN_ENDED") == {str(q2.id)}
    assert ids(search="alpha") == {str(q1.id)}
    assert ids(course_id=q3.course_id) == {str(q3.id)}


def test_filter_by_creator_ids_supports_repeated_and_comma_separated(auth_client, admin, ctx):
    t1, t2, t3 = (QuestionFactory(course=ctx["course"], module=ctx["module"]) for _ in range(3))
    client = auth_client(admin)
    a, b = t1.created_by_id, t2.created_by_id

    repeated = client.get(f"{QUESTIONS}?creator_ids={a}&creator_ids={b}").json()["data"]
    comma = client.get(f"{QUESTIONS}?creator_ids={a},{b}").json()["data"]
    expected = {str(t1.id), str(t2.id)}
    assert {q["id"] for q in repeated} == expected
    assert {q["id"] for q in comma} == expected
    assert str(t3.id) not in expected


def test_filter_by_invalid_creator_id_returns_422(auth_client, admin):
    response = auth_client(admin).get(QUESTIONS, {"creator_ids": "nope"})
    assert response.status_code == 422
    assert "creator_ids" in response.json()["errors"]


def test_list_is_paginated_newest_first(auth_client, admin, ctx):
    older = QuestionFactory(course=ctx["course"], module=ctx["module"])
    newer = QuestionFactory(course=ctx["course"], module=ctx["module"])
    body = auth_client(admin).get(QUESTIONS, {"limit": 1}).json()
    assert body["pagination"]["total"] == 2
    assert body["data"][0]["id"] == str(newer.id)
    assert older.id != newer.id
    assert Decimal(str(body["data"][0]["default_points"])) == Decimal("2")

"""JSON orqali savollar importi (XLSX ning JSON varianti)."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.academics.choices import CourseStatus
from apps.academics.tests.factories import CourseFactory, ModuleFactory
from apps.questions.json_import import AI_JSON_RULES, EXAMPLE_QUESTIONS
from apps.questions.models import Question
from apps.questions.tests.test_xlsx_import import QUESTIONS, import_ctx  # noqa: F401

pytestmark = pytest.mark.django_db
TEMPLATE = f"{QUESTIONS}/import-template-json"


def _template(auth_client, ctx) -> dict:
    response = auth_client(ctx["teacher"]).get(
        TEMPLATE, {"course_id": ctx["course"].id, "module_id": ctx["module"].id}
    )
    assert response.status_code == 200, response.content
    return json.loads(response.content.decode("utf-8"))


def _post(auth_client, ctx, payload, name="questions.json"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    upload = SimpleUploadedFile(name, raw, content_type="application/json")
    return auth_client(ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )


def _correct(text):
    return set(
        Question.objects.get(text=text)
        .options.filter(is_correct=True)
        .values_list("text", flat=True)
    )


# ------------------------------- shablon -------------------------------------
def test_json_template_contains_context_guide_and_examples(auth_client, import_ctx):  # noqa: F811
    response = auth_client(import_ctx["teacher"]).get(
        TEMPLATE,
        {"course_id": import_ctx["course"].id, "module_id": import_ctx["module"].id},
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["Content-Disposition"].endswith('.json"')
    data = json.loads(response.content.decode("utf-8"))
    assert data["format"] == "examtaker-questions" and data["version"] == 1
    assert data["course"] == {"id": str(import_ctx["course"].id), "name": import_ctx["course"].name}
    assert data["module"] == {
        "id": str(import_ctx["module"].id),
        "title": import_ctx["module"].title,
    }
    assert data["instructions"]["rules"] == AI_JSON_RULES
    assert "мои готовые вопросы" in data["instructions"]["prompt_ru"]
    assert data["example_questions"] == EXAMPLE_QUESTIONS
    assert data["questions"] == []


def test_json_template_respects_course_access_and_archive(auth_client, import_ctx):  # noqa: F811
    foreign = CourseFactory()
    response = auth_client(import_ctx["teacher"]).get(
        TEMPLATE, {"course_id": foreign.id, "module_id": ModuleFactory(course=foreign).id}
    )
    assert response.status_code == 403

    import_ctx["course"].status = CourseStatus.ARCHIVED
    import_ctx["course"].save(update_fields=["status"])
    response = auth_client(import_ctx["teacher"]).get(
        TEMPLATE,
        {"course_id": import_ctx["course"].id, "module_id": import_ctx["module"].id},
    )
    assert response.status_code == 400


# ------------------------------- import --------------------------------------
def test_filled_json_template_imports_all_types(auth_client, import_ctx):  # noqa: F811
    data = _template(auth_client, import_ctx)
    data["questions"] = [
        {
            "type": "SINGLE_CHOICE",
            "text": "len([1, 2, 3])?",
            "options": ["2", "3", "4"],
            "correct": ["B"],
            "points": 2,
        },
        {
            "type": "MULTIPLE_CHOICE",
            "text": "Immutable?",
            "options": ["list", "tuple", "str", "dict"],
            "correct": ["B", "C"],
            "points": 3,
        },
        {
            "type": "TRUE_FALSE",
            "text": "Indeks 0 dan?",
            "options": ["To'g'ri", "Noto'g'ri"],
            "correct": ["A"],
            "points": 1,
        },
        {"type": "OPEN_ENDED", "text": "Farqi?", "options": [], "correct": [], "points": 4},
        {"type": "PYTHON_CODE", "text": "sum_even", "options": [], "correct": [], "points": 5},
    ]
    response = _post(auth_client, import_ctx, data)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["created_count"] == 5  # example_questions import qilinmadi
    assert body["course_id"] == str(import_ctx["course"].id)
    assert body["module_id"] == str(import_ctx["module"].id)
    assert _correct("len([1, 2, 3])?") == {"3"}
    assert _correct("Immutable?") == {"tuple", "str"}
    assert _correct("Indeks 0 dan?") == {"To'g'ri"}
    assert Question.objects.get(text="sum_even").type == "PYTHON_CODE"
    assert str(Question.objects.get(text="Farqi?").default_points) == "4.00"


def test_examples_alone_are_not_imported(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, _template(auth_client, import_ctx))
    assert response.status_code == 422
    assert "topilmadi" in response.json()["errors"]["file"][0]
    assert Question.objects.count() == 0


def test_typical_ai_json_output_is_accepted(auth_client, import_ctx):  # noqa: F811
    """```json o‘rami, BOM, boshqacha kalitlar, variantlar dict/obyekt ko‘rinishida,
    javob matn/qator ko‘rinishida, `A) ` prefikslari, `Multiple choice`."""
    data = _template(auth_client, import_ctx)
    data["questions"] = [
        {"Type": "single choice", "question": "Q1", "options": ["A) 2", "B) 3"], "answer": "B"},
        {
            "type": "Multiple choice",
            "text": "Q2",
            "variants": {"A": "x", "B": "y", "C": "z"},
            "correct": "A, C",
            "ball": "2,5",
        },
        {
            "type": "SINGLE_CHOICE",
            "text": "Q3",
            "options": [
                {"text": "list", "is_correct": False},
                {"text": "tuple", "is_correct": True},
            ],
            "points": 2,
        },
        {
            "type": "TRUE_FALSE",
            "text": "Q4",
            "options": ["Ha", "Yo'q"],
            "correct": ["Ha"],
            "points": 1,
        },
        {},  # AI bo‘sh element qoldirgan
    ]
    data["questions"][0]["points"] = 2
    raw = b"\xef\xbb\xbf```json\n" + json.dumps(data, ensure_ascii=False).encode() + b"\n```"
    response = _post(auth_client, import_ctx, raw)
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 4
    assert _correct("Q1") == {"3"}
    assert sorted(Question.objects.get(text="Q1").options.values_list("text", flat=True)) == [
        "2",
        "3",
    ]
    assert _correct("Q2") == {"x", "z"}
    assert str(Question.objects.get(text="Q2").default_points) == "2.50"
    assert _correct("Q3") == {"tuple"}
    assert _correct("Q4") == {"Ha"}


def test_all_json_errors_reported_at_once(auth_client, import_ctx):  # noqa: F811
    data = _template(auth_client, import_ctx)
    data["questions"] = [
        {
            "type": "SINGLE_CHOICE",
            "text": "ok",
            "options": ["a", "b"],
            "correct": ["A"],
            "points": 2,
        },
        {
            "type": "SINGLE_CHOICE",
            "text": "?",
            "options": ["a", "b"],
            "correct": ["?"],
            "points": 2,
        },
        {
            "type": "SINGLE_CHOICE",
            "text": "C yo'q",
            "options": ["a", "b"],
            "correct": ["C"],
            "points": 2,
        },
        {
            "type": "SINGLE_CHOICE",
            "text": "7 variant",
            "options": list("abcdefg"),
            "correct": ["A"],
            "points": 2,
        },
        "matn",
    ]
    response = _post(auth_client, import_ctx, data)
    assert response.status_code == 422
    errors = response.json()["errors"]["file"]
    assert [error.split("-savol")[0] for error in errors] == ["2", "3", "4", "5"]
    assert "to'g'ri javob ko'rsatilmagan" in errors[0]
    assert Question.objects.count() == 0


def test_value_errors_use_question_numbers(auth_client, import_ctx):  # noqa: F811
    data = _template(auth_client, import_ctx)
    data["questions"] = [
        {"type": "SINGLE_CHOICE", "text": "", "options": ["a", "b"], "correct": ["A"], "points": 2},
        {
            "type": "SINGLE_CHOICE",
            "text": "ok",
            "options": ["a", "b"],
            "correct": ["A"],
            "points": 150,
        },
    ]
    response = _post(auth_client, import_ctx, data)
    assert response.status_code == 422
    rows = response.json()["errors"]["rows"]
    assert [item["row"] for item in rows] == ["1", "2"]
    assert "text" in rows[0]["errors"] and "default_points" in rows[1]["errors"]


@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"{not json", "JSON formati noto'g'ri"),
        (b"[]", "obyekt"),
        (json.dumps({"questions": []}).encode(), "course.id"),
        (
            json.dumps({"course": {"id": "x"}, "module": {"id": "y"}, "questions": {}}).encode(),
            '"questions"',
        ),
        ("слово".encode("cp1251"), "UTF-8"),
    ],
)
def test_broken_json_files_give_clear_errors(auth_client, import_ctx, payload, expected):  # noqa: F811
    response = _post(auth_client, import_ctx, payload)
    assert response.status_code == 422
    assert expected in response.json()["errors"]["file"][0]


def test_unknown_course_in_json_gives_actionable_message(auth_client, import_ctx):  # noqa: F811
    data = _template(auth_client, import_ctx)
    data["course"]["id"] = "00000000-0000-0000-0000-000000000001"
    data["questions"] = [
        {"type": "OPEN_ENDED", "text": "Q", "options": [], "correct": [], "points": 5}
    ]
    response = _post(auth_client, import_ctx, data)
    assert response.status_code == 422
    assert "course_id" in response.json()["errors"]


def test_only_xlsx_and_json_files_are_accepted(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, b"text", name="questions.txt")
    assert response.status_code == 422
    assert ".json" in response.json()["errors"]["file"][0]


@pytest.mark.parametrize("kind", ["deep", "huge_int"])
def test_hostile_json_gives_422_not_500(auth_client, import_ctx, kind):  # noqa: F811
    """Juda chuqur JSON va 4300+ xonali son oldin 500 (RecursionError/ValueError) berardi."""
    payload = b"[" * 100000 + b"]" * 100000 if kind == "deep" else b'{"a": ' + b"9" * 5000 + b"}"
    response = _post(auth_client, import_ctx, payload)
    assert response.status_code == 422
    assert "juda" in response.json()["errors"]["file"][0]

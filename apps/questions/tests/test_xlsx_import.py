from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook

from apps.academics.tests.factories import CourseFactory, CourseTeacherFactory, ModuleFactory
from apps.questions.choices import QuestionDifficulty
from apps.questions.models import Question
from apps.questions.xlsx import build_question_import_template

pytestmark = pytest.mark.django_db

QUESTIONS = "/api/v1/questions"


@pytest.fixture
def import_ctx(teacher):
    course = CourseFactory()
    CourseTeacherFactory(course=course, teacher=teacher)
    module = ModuleFactory(course=course)
    return {"course": course, "module": module, "teacher": teacher}


def xlsx_upload(import_ctx, *rows):
    content = build_question_import_template(
        course=import_ctx["course"], module=import_ctx["module"]
    )
    workbook = load_workbook(BytesIO(content))
    sheet = workbook["Savollar"]
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return SimpleUploadedFile(
        "questions.xlsx",
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def test_download_template_contains_course_module_and_examples(auth_client, import_ctx):
    response = auth_client(import_ctx["teacher"]).get(
        f"{QUESTIONS}/import-template",
        {
            "course_id": import_ctx["course"].id,
            "module_id": import_ctx["module"].id,
        },
    )

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
    assert workbook.sheetnames == ["Ma'lumot", "Savollar", "Namuna"]
    assert workbook["Ma'lumot"]["B2"].value == str(import_ctx["course"].id)
    assert workbook["Ma'lumot"]["B3"].value == import_ctx["course"].name
    assert workbook["Ma'lumot"]["B4"].value == str(import_ctx["module"].id)
    assert workbook["Ma'lumot"]["B5"].value == import_ctx["module"].title
    assert workbook["Namuna"].max_row == 5


def test_imports_single_choice_from_xlsx(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [
            1,
            "SINGLE_CHOICE",
            "2 + 2 nechiga teng?",
            "3",
            "4",
            "5",
            "6",
            None,
            None,
            "B",
            4,
        ],
    )

    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )

    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 1
    question = Question.objects.get()
    assert question.course == import_ctx["course"]
    assert question.module == import_ctx["module"]
    assert question.created_by == import_ctx["teacher"]
    assert question.default_points == 4
    assert question.difficulty == QuestionDifficulty.MEDIUM
    assert list(question.options.values_list("text", "is_correct")) == [
        ("3", False),
        ("4", True),
        ("5", False),
        ("6", False),
    ]


def test_invalid_row_rejects_whole_xlsx(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, "SINGLE_CHOICE", "Valid", "A", "B", None, None, None, None, "A", 2],
        [2, "SINGLE_CHOICE", "Invalid", "A", "B", None, None, None, None, "A,B", 2],
    )

    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )

    assert response.status_code == 422
    assert response.json()["errors"]["rows"][0]["row"] == "3"
    assert Question.objects.count() == 0


def test_teacher_cannot_use_template_for_unassigned_course(auth_client, import_ctx):
    foreign_course = CourseFactory()
    foreign_module = ModuleFactory(course=foreign_course)

    response = auth_client(import_ctx["teacher"]).get(
        f"{QUESTIONS}/import-template",
        {"course_id": foreign_course.id, "module_id": foreign_module.id},
    )

    assert response.status_code == 403


def test_rejects_non_xlsx_file(auth_client, import_ctx):
    upload = SimpleUploadedFile(
        "questions.xlsx",
        b"not an xlsx file",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )

    assert response.status_code == 422
    assert "XLSX" in response.json()["errors"]["file"][0]


def test_import_requires_points(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, "SINGLE_CHOICE", "No points", "A", "B", None, None, None, None, "A", None],
    )

    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )

    assert response.status_code == 422
    assert "default_points" in response.json()["errors"]["rows"][0]["errors"]
    assert Question.objects.count() == 0

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
    assert workbook.sheetnames == ["Ma'lumot", "Savollar", "Namuna", "AI uchun yo'riqnoma"]
    assert workbook["Ma'lumot"]["B2"].value == str(import_ctx["course"].id)
    assert workbook["Ma'lumot"]["B3"].value == import_ctx["course"].name
    assert workbook["Ma'lumot"]["B4"].value == str(import_ctx["module"].id)
    assert workbook["Ma'lumot"]["B5"].value == import_ctx["module"].title
    assert workbook["Namuna"].max_row == 6  # 5 ta tur bo‘yicha misol


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


def test_imports_all_supported_question_types(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, "SINGLE_CHOICE", "Single", "A", "B", None, None, None, None, "A", 2],
        [
            2,
            "MULTIPLE_CHOICE",
            "Multiple",
            "A",
            "B",
            "C",
            None,
            None,
            None,
            "A,C",
            3,
        ],
        [
            3,
            "TRUE_FALSE",
            "True or false",
            "To'g'ri",
            "Noto'g'ri",
            None,
            None,
            None,
            None,
            "B",
            1,
        ],
        [4, "OPEN_ENDED", "Open", None, None, None, None, None, None, None, 5],
    )

    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )

    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 4
    questions = {
        question.text: question for question in Question.objects.prefetch_related("options")
    }
    assert questions["Single"].type == "SINGLE_CHOICE"
    assert questions["Multiple"].type == "MULTIPLE_CHOICE"
    assert questions["True or false"].type == "TRUE_FALSE"
    assert questions["Open"].type == "OPEN_ENDED"
    assert set(
        questions["Multiple"].options.filter(is_correct=True).values_list("text", flat=True)
    ) == {"A", "C"}
    assert list(
        questions["True or false"].options.filter(is_correct=True).values_list("text", flat=True)
    ) == ["Noto'g'ri"]
    assert not questions["Open"].options.exists()


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


def test_teacher_cannot_import_into_unassigned_course(auth_client, import_ctx):
    foreign_course = CourseFactory()
    foreign_ctx = {
        "course": foreign_course,
        "module": ModuleFactory(course=foreign_course),
    }
    upload = xlsx_upload(
        foreign_ctx,
        [1, "SINGLE_CHOICE", "Forbidden", "A", "B", None, None, None, None, "A", 2],
    )

    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )

    assert response.status_code == 403
    assert Question.objects.count() == 0


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


# --------------------------------------------------------------------------
# Haqiqiy Excel / Google Sheets fayllari (prod'da to‘g‘ri fayllar rad etilgan holatlar)
# --------------------------------------------------------------------------
def _template_workbook(import_ctx):
    content = build_question_import_template(
        course=import_ctx["course"], module=import_ctx["module"]
    )
    return load_workbook(BytesIO(content))


def _as_upload(content: bytes, name="questions.xlsx"):
    return SimpleUploadedFile(
        name,
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _save(workbook) -> bytes:
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _import(auth_client, import_ctx, content: bytes):
    return auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": _as_upload(content)}, format="multipart"
    )


SINGLE = [1, "SINGLE_CHOICE", "2 + 2?", "3", "4", None, None, None, None, "B", 2]


def test_formatted_empty_rows_do_not_count_towards_limit(auth_client, import_ctx):
    """Formatlash 1000-qatorgacha tortilgan: 1 ta savol bo‘lsa ham import bo‘lishi kerak."""
    from openpyxl.styles import Font

    workbook = _template_workbook(import_ctx)
    sheet = workbook["Savollar"]
    sheet.append(SINGLE)
    for row in range(3, 1001):
        sheet.cell(row=row, column=1).font = Font(bold=True)

    response = _import(auth_client, import_ctx, _save(workbook))
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 1


def test_file_without_dimension_tag_is_accepted(auth_client, import_ctx):
    import re
    import zipfile

    workbook = _template_workbook(import_ctx)
    workbook["Savollar"].append(SINGLE)
    source = zipfile.ZipFile(BytesIO(_save(workbook)))
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                data = re.sub(rb"<dimension[^>]*/>", b"", data)
            target.writestr(item, data)

    response = _import(auth_client, import_ctx, output.getvalue())
    assert response.status_code == 201, response.json()


def test_more_than_500_filled_rows_still_rejected(auth_client, import_ctx):
    workbook = _template_workbook(import_ctx)
    sheet = workbook["Savollar"]
    for index in range(501):
        sheet.append([index, "SINGLE_CHOICE", f"Q{index}", "a", "b", *[None] * 4, "A", 1])

    response = _import(auth_client, import_ctx, _save(workbook))
    assert response.status_code == 422
    assert "500" in response.json()["errors"]["file"][0]
    assert Question.objects.count() == 0


def test_answer_letters_accept_lowercase_joined_and_cyrillic(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, "MULTIPLE_CHOICE", "Lower", "a", "b", "c", None, None, None, "a, c", 2],
        [2, "MULTIPLE_CHOICE", "Joined", "a", "b", "c", None, None, None, "AC", 2],
        [3, "SINGLE_CHOICE", "Cyrillic", "a", "b", "c", None, None, None, "В", 2],
    )
    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )
    assert response.status_code == 201, response.json()

    def correct(text):
        return set(
            Question.objects.get(text=text)
            .options.filter(is_correct=True)
            .values_list("text", flat=True)
        )

    assert correct("Lower") == {"a", "c"}
    assert correct("Joined") == {"a", "c"}
    assert correct("Cyrillic") == {"b"}


def test_type_spelling_variants_and_comma_decimal_points(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, " single choice ", "Spaces", "a", "b", None, None, None, None, "A", "2,5"],
        [2, "True-False", "Hyphen", "Ha", "Yo'q", None, None, None, None, "A", 1],
    )
    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )
    assert response.status_code == 201, response.json()
    spaces = Question.objects.get(text="Spaces")
    assert spaces.type == "SINGLE_CHOICE"
    assert str(spaces.default_points) == "2.50"
    assert Question.objects.get(text="Hyphen").type == "TRUE_FALSE"


def test_imports_python_code_question(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, "PYTHON_CODE", "Print 5", None, None, None, None, None, None, None, 5],
    )
    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )
    assert response.status_code == 201, response.json()
    question = Question.objects.get()
    assert question.type == "PYTHON_CODE"
    assert not question.options.exists()


def test_python_code_with_answer_letter_is_rejected(auth_client, import_ctx):
    upload = xlsx_upload(
        import_ctx,
        [1, "PYTHON_CODE", "Print 5", "x", None, None, None, None, None, "A", 5],
    )
    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )
    assert response.status_code == 422
    assert "PYTHON_CODE" in response.json()["errors"]["file"][0]


def test_unknown_course_id_gives_actionable_message(auth_client, import_ctx):
    workbook = _template_workbook(import_ctx)
    workbook["Savollar"].append(SINGLE)
    workbook["Ma'lumot"]["B2"] = "00000000-0000-0000-0000-000000000001"

    response = _import(auth_client, import_ctx, _save(workbook))
    assert response.status_code == 422
    message = response.json()["errors"]["course_id"][0]
    assert "import-template" in message
    assert Question.objects.count() == 0


def test_all_answer_letter_errors_are_reported_at_once(auth_client, import_ctx):
    """Ustoz faylni har bir xato uchun qayta-qayta yuklamasligi kerak."""
    upload = xlsx_upload(
        import_ctx,
        [1, "SINGLE_CHOICE", "Q1", "a", "b", None, None, None, None, "C", 2],
        [2, "SINGLE_CHOICE", "Valid", "a", "b", None, None, None, None, "A", 2],
        [3, "SINGLE_CHOICE", "Q3", "a", "b", None, None, None, None, "D", 2],
        [4, "OPEN_ENDED", "Q4", None, None, None, None, None, None, "A", 2],
    )
    response = auth_client(import_ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )
    assert response.status_code == 422
    errors = response.json()["errors"]["file"]  # kalit va tip (ro‘yxat) o‘zgarmagan
    assert [error.split("-qator")[0] for error in errors] == ["2", "4", "5"]
    assert Question.objects.count() == 0

"""`docs/xlsx_test/` dagi qo‘lda test qilish fayllari hujjatda yozilgandek ishlashini tekshiradi."""

from io import BytesIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook

from apps.questions.models import Question
from apps.questions.tests.test_xlsx_import import QUESTIONS, import_ctx  # noqa: F401

pytestmark = pytest.mark.django_db

FILES = Path(settings.BASE_DIR) / "docs" / "xlsx_test"


def _upload(name: str, ctx=None) -> SimpleUploadedFile:
    workbook = load_workbook(FILES / name)
    if ctx is not None:  # foydalanuvchi qo‘lda qiladigan ish: 2 ta katakka ID yozish
        workbook["Ma'lumot"]["B2"] = str(ctx["course"].id)
        workbook["Ma'lumot"]["B4"] = str(ctx["module"].id)
    output = BytesIO()
    workbook.save(output)
    return SimpleUploadedFile(name, output.getvalue())


def _post(auth_client, ctx, upload):
    return auth_client(ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )


def test_valid_file_imports_all_12_questions(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, _upload("1_togri_savollar.xlsx", import_ctx))
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 12
    types = sorted(set(Question.objects.values_list("type", flat=True)))
    assert types == [
        "MULTIPLE_CHOICE",
        "OPEN_ENDED",
        "PYTHON_CODE",
        "SINGLE_CHOICE",
        "TRUE_FALSE",
    ]


def test_letter_errors_file_reports_all_four_at_once(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, _upload("2_xatoli_javob_harflari.xlsx", import_ctx))
    assert response.status_code == 422
    rows = [error.split("-qator")[0] for error in response.json()["errors"]["file"]]
    assert rows == ["3", "4", "5", "6"]
    assert Question.objects.count() == 0


def test_value_errors_file_reports_every_row(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, _upload("3_xatoli_qiymatlar.xlsx", import_ctx))
    assert response.status_code == 422
    rows = [item["row"] for item in response.json()["errors"]["rows"]]
    assert rows == [str(number) for number in range(2, 10)]
    assert Question.objects.count() == 0


def test_file_without_real_ids_gives_actionable_message(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, _upload("1_togri_savollar.xlsx"))
    assert response.status_code == 422
    assert "import-template" in response.json()["errors"]["course_id"][0]
    assert Question.objects.count() == 0


def test_exam_5_file_imports_one_question_of_each_type(auth_client, import_ctx):  # noqa: F811
    response = _post(auth_client, import_ctx, _upload("exam_5_savol.xlsx", import_ctx))
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 5
    by_type = {question.type: question for question in Question.objects.all()}
    assert sorted(by_type) == [
        "MULTIPLE_CHOICE",
        "OPEN_ENDED",
        "PYTHON_CODE",
        "SINGLE_CHOICE",
        "TRUE_FALSE",
    ]
    assert sum(q.default_points for q in by_type.values()) == 15
    correct = set(
        by_type["MULTIPLE_CHOICE"].options.filter(is_correct=True).values_list("text", flat=True)
    )
    assert correct == {"tuple", "str"}


def test_exam_5_json_file_imports_one_question_of_each_type(auth_client, import_ctx):  # noqa: F811
    import json

    data = json.loads((FILES / "exam_5_savol.json").read_text(encoding="utf-8"))
    data["course"]["id"] = str(import_ctx["course"].id)
    data["module"]["id"] = str(import_ctx["module"].id)
    upload = SimpleUploadedFile("exam_5_savol.json", json.dumps(data).encode("utf-8"))
    response = _post(auth_client, import_ctx, upload)
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 5
    assert sorted({q.type for q in Question.objects.all()}) == [
        "MULTIPLE_CHOICE",
        "OPEN_ENDED",
        "PYTHON_CODE",
        "SINGLE_CHOICE",
        "TRUE_FALSE",
    ]

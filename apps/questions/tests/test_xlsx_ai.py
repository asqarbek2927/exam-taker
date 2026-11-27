"""AI (ChatGPT va h.k.) to‘ldirgan XLSX fayllar: shablondagi yo‘riqnoma va importning
AI odatiy "xatolari"ga bardoshliligi."""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook, load_workbook

from apps.questions.models import Question
from apps.questions.tests.test_xlsx_import import QUESTIONS, import_ctx  # noqa: F401
from apps.questions.xlsx import (
    AI_GUIDE_SHEET,
    AI_RULES,
    QUESTION_HEADERS,
    build_question_import_template,
)

pytestmark = pytest.mark.django_db
N = None


def _template(ctx):
    content = build_question_import_template(course=ctx["course"], module=ctx["module"])
    return load_workbook(BytesIO(content))


def _post(auth_client, ctx, workbook):
    output = BytesIO()
    workbook.save(output)
    upload = SimpleUploadedFile("ai.xlsx", output.getvalue())
    return auth_client(ctx["teacher"]).post(
        f"{QUESTIONS}/import", {"file": upload}, format="multipart"
    )


def _correct(text):
    return set(
        Question.objects.get(text=text)
        .options.filter(is_correct=True)
        .values_list("text", flat=True)
    )


# ------------------------------- A: yo‘riqnoma -------------------------------
def test_template_has_ai_guide_with_prompts_and_rules(auth_client, import_ctx):  # noqa: F811
    response = auth_client(import_ctx["teacher"]).get(
        f"{QUESTIONS}/import-template",
        {"course_id": import_ctx["course"].id, "module_id": import_ctx["module"].id},
    )
    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content))
    assert AI_GUIDE_SHEET in workbook.sheetnames
    text = "\n".join(
        str(cell.value)
        for row in workbook[AI_GUIDE_SHEET].iter_rows()
        for cell in row
        if cell.value
    )
    # AI o‘zi savol yaratmaydi — ustozning tayyor savollarini ko‘chiradi (o‘zbekcha va ruscha).
    assert "mening tayyor savollarim" in text and "мои готовые вопросы" in text
    assert "Yangi savol qo'shma" in text
    assert "[MAVZU]" not in text and "[ТЕМА]" not in text
    assert "TAXMIN QILMA" in text  # javob ko‘rsatilmagan bo‘lsa `?`
    for rule in AI_RULES:
        assert rule in text


def test_template_with_guide_untouched_still_imports(auth_client, import_ctx):  # noqa: F811
    workbook = _template(import_ctx)
    workbook["Savollar"].append([1, "SINGLE_CHOICE", "Q", "a", "b", N, N, N, N, "A", 2])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 1


# --------------------------- C: AI odatlari -------------------------------------
def test_typical_ai_output_is_accepted(auth_client, import_ctx):  # noqa: F811
    """Qayta nomlangan varaqlar, "aqlli" tirnoqlar, `B)` javoblar, matnli javoblar,
    `A) ` prefiksli variantlar — hammasi bitta faylda."""
    workbook = _template(import_ctx)
    workbook["Ma'lumot"].title = "Ma’lumot"  # AI tirnoqni almashtirgan
    sheet = workbook["Savollar"]
    sheet.title = "Questions"  # AI varaqni qayta nomlagan
    sheet["J1"] = "To‘g‘ri javob"  # "aqlli" tirnoqlar
    rows = [
        [1, "single choice", "len([1,2,3])?", "A) 2", "B) 3", "C) 4", N, N, N, "B)", 2],
        [2, "MULTIPLE_CHOICE", "Immutable?", "list", "tuple", "str", "dict", N, N, "tuple, str", 3],
        [3, "TRUE_FALSE", "Indeks 0 dan?", "To'g'ri", "Noto'g'ri", N, N, N, N, "To‘g‘ri", 1],
        [4, "Multiple choice", "Juft sonlar?", "2", "3", "4", N, N, N, "(A), (C)", 2],
        [5, "Python code", "sum_even yozing", N, N, N, N, N, N, N, 5],
    ]
    for row in rows:
        sheet.append(row)

    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 5  # Namuna import qilinmadi
    assert _correct("len([1,2,3])?") == {"3"}
    assert sorted(
        Question.objects.get(text="len([1,2,3])?").options.values_list("text", flat=True)
    ) == ["2", "3", "4"]  # "A) " prefikslari olib tashlandi
    assert _correct("Immutable?") == {"tuple", "str"}
    assert _correct("Indeks 0 dan?") == {"To'g'ri"}
    assert _correct("Juft sonlar?") == {"2", "4"}
    assert Question.objects.get(text="sum_even yozing").type == "PYTHON_CODE"


def test_info_ids_found_by_label_when_ai_moves_rows(auth_client, import_ctx):  # noqa: F811
    """AI `Ma'lumot` varag‘ini qayta yozib, qatorlar joyini o‘zgartirgan."""
    workbook = _template(import_ctx)
    info = workbook["Ma'lumot"]
    info.delete_rows(1, info.max_row)
    info.append(["Kurs nomi", "x"])
    info.append(["Modul ID", str(import_ctx["module"].id)])
    info.append(["Kurs ID", str(import_ctx["course"].id)])
    workbook["Savollar"].append([1, "SINGLE_CHOICE", "Q", "a", "b", N, N, N, N, "A", 2])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 201, response.json()


def test_partial_option_prefixes_are_kept(auth_client, import_ctx):  # noqa: F811
    """Faqat ba’zi variantlarda prefiks bo‘lsa — matnga tegilmaydi."""
    workbook = _template(import_ctx)
    workbook["Savollar"].append([1, "SINGLE_CHOICE", "Prefix", "A) ha", "yo'q", N, N, N, N, "A", 2])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 201, response.json()
    assert _correct("Prefix") == {"A) ha"}


def test_letter_wins_over_option_text(auth_client, import_ctx):  # noqa: F811
    """Variantlar "B", "A" bo‘lsa, javob `A` — hujjatdagi qoida bo‘yicha 1-variant."""
    workbook = _template(import_ctx)
    workbook["Savollar"].append([1, "SINGLE_CHOICE", "Harflar", "B", "A", N, N, N, N, "A", 2])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 201, response.json()
    assert _correct("Harflar") == {"B"}


def test_unmatched_text_answer_still_reported(auth_client, import_ctx):  # noqa: F811
    workbook = _template(import_ctx)
    workbook["Savollar"].append([1, "SINGLE_CHOICE", "Q", "list", "tuple", N, N, N, N, "set", 2])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 422
    assert "mavjud bo'lmagan" in response.json()["errors"]["file"][0]
    assert Question.objects.count() == 0


def test_ambiguous_question_sheets_are_rejected(auth_client, import_ctx):  # noqa: F811
    """`Savollar` yo‘q va mos sarlavhali varaq bir nechta — qaysi biri ekanini taxmin qilmaymiz."""
    workbook = _template(import_ctx)
    workbook["Savollar"].title = "Part 1"
    extra = workbook.create_sheet("Part 2")
    extra.append(QUESTION_HEADERS)
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 422
    assert "topilmadi" in response.json()["errors"]["file"][0]


def test_file_without_info_sheet_gives_clear_message(auth_client, import_ctx):  # noqa: F811
    """AI faylni noldan yaratib, `Ma'lumot` ni tashlab yuborgan."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Savollar"
    sheet.append(QUESTION_HEADERS)
    sheet.append([1, "SINGLE_CHOICE", "Q", "a", "b", N, N, N, N, "A", 2])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 422
    assert "Ma'lumot" in response.json()["errors"]["file"][0]


# ------------------------- `?` — manbada javob yo‘q ----------------------------
def test_question_mark_answer_is_reported_not_guessed(auth_client, import_ctx):  # noqa: F811
    """AI javobni taxmin qilmay `?` yozgan qatorlar aniq xato bilan qaytadi."""
    workbook = _template(import_ctx)
    sheet = workbook["Savollar"]
    sheet.append([1, "SINGLE_CHOICE", "Javobi bor", "a", "b", N, N, N, N, "A", 2])
    sheet.append([2, "SINGLE_CHOICE", "Javobi yo'q", "a", "b", N, N, N, N, "?", 2])
    sheet.append([3, "MULTIPLE_CHOICE", "Qisman", "a", "b", "c", N, N, N, "A,?", 3])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 422
    errors = response.json()["errors"]["file"]
    assert [error.split("-qator")[0] for error in errors] == ["3", "4"]
    assert all("to'g'ri javob ko'rsatilmagan" in error for error in errors)
    assert Question.objects.count() == 0


def test_question_mark_on_open_and_code_questions_is_ignored(auth_client, import_ctx):  # noqa: F811
    """OPEN_ENDED / PYTHON_CODE da javob ustuni baribir bo‘sh — `?` xalaqit bermaydi."""
    workbook = _template(import_ctx)
    sheet = workbook["Savollar"]
    sheet.append([1, "OPEN_ENDED", "Tushuntiring", N, N, N, N, N, N, "?", 5])
    sheet.append([2, "PYTHON_CODE", "Kod yozing", N, N, N, N, N, N, "?", 5])
    response = _post(auth_client, import_ctx, workbook)
    assert response.status_code == 201, response.json()
    assert response.json()["created_count"] == 2

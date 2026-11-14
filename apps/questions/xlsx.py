"""Question bank uchun XLSX shablon yaratish va import faylini o'qish."""

import re
from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException

from apps.academics.models import Course, Module

from .choices import QuestionType

INFO_SHEET = "Ma'lumot"
QUESTIONS_SHEET = "Savollar"
EXAMPLE_SHEET = "Namuna"
MAX_IMPORT_ROWS = 500
OPTION_LETTERS = ("A", "B", "C", "D", "E", "F")
QUESTION_HEADERS = [
    "T/r",
    "Turi",
    "Savol",
    *[f"Variant {letter}" for letter in OPTION_LETTERS],
    "To'g'ri javob",
    "Ball",
]


class QuestionXLSXError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedQuestionRow:
    row: int
    data: dict


@dataclass(frozen=True)
class ParsedQuestionWorkbook:
    course_id: str
    module_id: str
    questions: list[ParsedQuestionRow]


def _style_header(sheet) -> None:
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:K1"
    widths = [8, 22, 55, 24, 24, 24, 24, 24, 24, 22, 12]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width


def _add_example_rows(sheet) -> None:
    rows = [
        [
            1,
            "SINGLE_CHOICE",
            "Python asoschisi kim?",
            "Guido van Rossum",
            "Elon Musk",
            "Bill Gates",
            "Linus Torvalds",
            None,
            None,
            "A",
            2,
        ],
        [
            2,
            "MULTIPLE_CHOICE",
            "Qaysilari dasturlash tili?",
            "Python",
            "HTML",
            "Java",
            "CSS",
            None,
            None,
            "A,C",
            3,
        ],
        [
            3,
            "TRUE_FALSE",
            "Django Python framework hisoblanadi.",
            "To'g'ri",
            "Noto'g'ri",
            None,
            None,
            None,
            None,
            "A",
            1,
        ],
        [4, "OPEN_ENDED", "HTTP nima?", None, None, None, None, None, None, None, 5],
    ]
    for row in rows:
        sheet.append(row)


def build_question_import_template(*, course: Course, module: Module) -> bytes:
    workbook = Workbook()
    info = workbook.active
    info.title = INFO_SHEET
    info.append(["Maydon", "Qiymat", "Izoh"])
    info.append(["Kurs ID", str(course.id), "O'zgartirmang"])
    info.append(["Kurs nomi", course.name, "Ma'lumot uchun"])
    info.append(["Modul ID", str(module.id), "O'zgartirmang"])
    info.append(["Modul nomi", module.title, "Ma'lumot uchun"])
    info.append(["Qoida", "Faqat 'Savollar' varag'ini to'ldiring", "'Namuna' import qilinmaydi"])
    info.column_dimensions["A"].width = 20
    info.column_dimensions["B"].width = 50
    info.column_dimensions["C"].width = 45
    _style_header(info)

    questions = workbook.create_sheet(QUESTIONS_SHEET)
    questions.append(QUESTION_HEADERS)
    _style_header(questions)

    example = workbook.create_sheet(EXAMPLE_SHEET)
    example.append(QUESTION_HEADERS)
    _add_example_rows(example)
    _style_header(example)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _correct_letters(value) -> set[str]:
    raw = _text(value).upper()
    if not raw:
        return set()
    return {part for part in re.split(r"[,;\s]+", raw) if part}


def parse_question_import(file_obj) -> ParsedQuestionWorkbook:
    try:
        workbook = load_workbook(file_obj, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError, KeyError) as exc:
        raise QuestionXLSXError("Fayl yaroqli XLSX hujjat emas.") from exc

    if INFO_SHEET not in workbook.sheetnames or QUESTIONS_SHEET not in workbook.sheetnames:
        raise QuestionXLSXError(
            "XLSX formati noto'g'ri. Shablonni `import-template` endpointidan yuklab oling."
        )

    info = workbook[INFO_SHEET]
    course_id = _text(info["B2"].value)
    module_id = _text(info["B4"].value)
    if not course_id or not module_id:
        raise QuestionXLSXError("XLSX ichida Kurs ID va Modul ID bo'lishi shart.")

    sheet = workbook[QUESTIONS_SHEET]
    if [_text(cell.value) for cell in sheet[1]][: len(QUESTION_HEADERS)] != QUESTION_HEADERS:
        raise QuestionXLSXError("`Savollar` varag'idagi ustun nomlari o'zgartirilgan.")
    if sheet.max_row - 1 > MAX_IMPORT_ROWS:
        raise QuestionXLSXError(
            f"Bitta faylda ko'pi bilan {MAX_IMPORT_ROWS} ta savol bo'lishi mumkin."
        )

    questions: list[ParsedQuestionRow] = []
    for row_number, values in enumerate(
        sheet.iter_rows(min_row=2, max_col=len(QUESTION_HEADERS), values_only=True), start=2
    ):
        _, question_type, question_text, *tail = values
        option_values = tail[: len(OPTION_LETTERS)]
        correct_value, points = tail[len(OPTION_LETTERS) :]
        if not any(_text(value) for value in values):
            continue

        question_type = _text(question_type).upper()
        options_by_letter = {
            letter: _text(value)
            for letter, value in zip(OPTION_LETTERS, option_values, strict=True)
            if _text(value)
        }
        correct = _correct_letters(correct_value)
        unknown_answers = correct - options_by_letter.keys()
        if unknown_answers:
            bad = ", ".join(sorted(unknown_answers))
            raise QuestionXLSXError(
                f"{row_number}-qator: javob ({bad}) mavjud bo'lmagan variantni ko'rsatgan."
            )
        if question_type == QuestionType.OPEN_ENDED and correct:
            raise QuestionXLSXError(
                f"{row_number}-qator: OPEN_ENDED savolda to'g'ri javob harfi bo'lmasligi kerak."
            )

        options = [
            {"text": text, "is_correct": letter in correct}
            for letter, text in options_by_letter.items()
        ]
        questions.append(
            ParsedQuestionRow(
                row=row_number,
                data={
                    "type": question_type,
                    "text": _text(question_text),
                    "options": options,
                    "default_points": points,
                },
            )
        )

    if not questions:
        raise QuestionXLSXError("`Savollar` varag'ida import qilinadigan savol topilmadi.")
    return ParsedQuestionWorkbook(
        course_id=course_id,
        module_id=module_id,
        questions=questions,
    )

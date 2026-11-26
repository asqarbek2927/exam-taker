"""Question bank uchun XLSX shablon yaratish va import faylini o'qish."""

import re
from dataclasses import dataclass
from io import BytesIO
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException

from apps.academics.models import Course, Module

from .choices import MANUAL_GRADED_TYPES

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
    """Import xatosi. `messages` — barcha xatolar (bir nechta qatorda xato bo‘lsa ham)."""

    def __init__(self, message: str | list[str]):
        self.messages = [message] if isinstance(message, str) else list(message)
        super().__init__("; ".join(self.messages))


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
            "Kuchli parol qaysi javobda to'g'ri ko'rsatilgan?",
            "12345678",
            "Azizbek2005",
            "T7#mQ2!zLp9@",
            "password",
            None,
            None,
            "C",
            2,
        ],
        [
            2,
            "MULTIPLE_CHOICE",
            "Qaysilari phishing xabarining belgilaridir?",
            "Shoshilinch havolani bosish talabi",
            "Shubhali yoki xato yozilgan domen",
            "Parolni yuborishni so'rash",
            "Oldindan kelishilgan rasmiy xabar",
            None,
            None,
            "A,B,C",
            3,
        ],
        [
            3,
            "TRUE_FALSE",
            "HTTPS internet orqali yuborilayotgan ma'lumotlarni shifrlaydi.",
            "To'g'ri",
            "Noto'g'ri",
            None,
            None,
            None,
            None,
            "A",
            1,
        ],
        [
            4,
            "OPEN_ENDED",
            "Ikki faktorli autentifikatsiya nima va u nima uchun kerak?",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            5,
        ],
        [
            5,
            "PYTHON_CODE",
            "Ikki sonni qo'shib natijani chiqaradigan Python funksiyasini yozing.",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            5,
        ],
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
    info.append(
        [
            "Turlar",
            "SINGLE_CHOICE, MULTIPLE_CHOICE, TRUE_FALSE, OPEN_ENDED, PYTHON_CODE",
            "OPEN_ENDED va PYTHON_CODE: variant va javob harfi bo'sh",
        ]
    )
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


# Rus klaviaturasida yozilgan, lotin harfiga aynan o‘xshash kirill harflari.
_CYRILLIC_LOOKALIKES = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E"})


def _correct_letters(value) -> set[str]:
    """`A`, `a, c`, `A;C`, `A C`, `AC`, kirillcha `А` — hammasi qabul qilinadi."""
    raw = _text(value).upper().translate(_CYRILLIC_LOOKALIKES)
    if not raw:
        return set()
    letters: set[str] = set()
    for part in re.split(r"[,;/\s]+", raw):
        if not part:
            continue
        if len(part) > 1 and set(part) <= set(OPTION_LETTERS):
            letters.update(part)  # "AC" -> A, C
        else:
            letters.add(part)
    return letters


def _question_type(value) -> str:
    """`single choice`, `Single-Choice`, ` SINGLE_CHOICE ` -> `SINGLE_CHOICE`."""
    return re.sub(r"[\s\-/]+", "_", _text(value).upper()).strip("_")


def _points(value):
    """Matn ko‘rinishidagi `2,5` (vergulli kasr) -> `2.5`. Raqamlar o‘zgarmaydi."""
    if isinstance(value, str):
        return value.strip().replace(",", ".")
    return value


def _parse_loaded_workbook(workbook) -> ParsedQuestionWorkbook:
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
    width = len(QUESTION_HEADERS)
    header = next(sheet.iter_rows(min_row=1, max_row=1, max_col=width, values_only=True), ())
    if [_text(value) for value in header] != QUESTION_HEADERS:
        raise QuestionXLSXError("`Savollar` varag'idagi ustun nomlari o'zgartirilgan.")

    # `sheet.max_row` ishlatilmaydi: Excel/Google Sheets formatlangan bo‘sh qatorlarni ham
    # yozadi (max_row=1000), ba’zi dasturlar esa `<dimension>` ni umuman yozmaydi (None).
    # Shuning uchun faqat to‘ldirilgan qatorlar sanaladi.
    questions: list[ParsedQuestionRow] = []
    row_errors: list[str] = []  # hamma qatordagi xatolar birdaniga qaytariladi
    filled_rows = 0
    for row_number, row in enumerate(
        sheet.iter_rows(min_row=2, max_col=width, values_only=True), start=2
    ):
        values = (tuple(row) + (None,) * width)[:width]
        if not any(_text(value) for value in values):
            continue
        filled_rows += 1
        if filled_rows > MAX_IMPORT_ROWS:
            raise QuestionXLSXError(
                f"Bitta faylda ko'pi bilan {MAX_IMPORT_ROWS} ta savol bo'lishi mumkin."
            )
        _, question_type, question_text, *tail = values
        option_values = tail[: len(OPTION_LETTERS)]
        correct_value, points = tail[len(OPTION_LETTERS) :]

        question_type = _question_type(question_type)
        options_by_letter = {
            letter: _text(value)
            for letter, value in zip(OPTION_LETTERS, option_values, strict=True)
            if _text(value)
        }
        correct = _correct_letters(correct_value)
        unknown_answers = correct - options_by_letter.keys()
        if question_type in MANUAL_GRADED_TYPES and correct:
            row_errors.append(
                f"{row_number}-qator: {question_type} savolda to'g'ri javob harfi "
                "bo'lmasligi kerak."
            )
            continue
        if unknown_answers:
            bad = ", ".join(sorted(unknown_answers))
            row_errors.append(
                f"{row_number}-qator: javob ({bad}) mavjud bo'lmagan variantni ko'rsatgan."
            )
            continue

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
                    "default_points": _points(points),
                },
            )
        )

    if row_errors:
        raise QuestionXLSXError(row_errors)
    if not questions:
        raise QuestionXLSXError("`Savollar` varag'ida import qilinadigan savol topilmadi.")
    return ParsedQuestionWorkbook(
        course_id=course_id,
        module_id=module_id,
        questions=questions,
    )


def parse_question_import(file_obj) -> ParsedQuestionWorkbook:
    workbook = None
    try:
        workbook = load_workbook(file_obj, read_only=True, data_only=True)
        return _parse_loaded_workbook(workbook)
    except QuestionXLSXError:
        raise
    except (
        BadZipFile,
        IndexError,
        InvalidFileException,
        KeyError,
        OSError,
        ParseError,
        TypeError,
        ValueError,
    ) as exc:
        raise QuestionXLSXError("Fayl yaroqli XLSX hujjat emas.") from exc
    finally:
        if workbook is not None:
            workbook.close()

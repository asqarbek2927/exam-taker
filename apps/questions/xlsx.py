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
AI_GUIDE_SHEET = "AI uchun yo'riqnoma"
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


AI_PROMPT_UZ = (
    "Senga ikkita fayl beryapman: 1) ExamTaker shabloni (.xlsx), 2) mening tayyor savollarim. "
    "Mening savollarimni shablondagi \"AI uchun yo'riqnoma\" varag'idagi qoidalarga qat'iy "
    "amal qilib \"Savollar\" varag'iga ko'chir. Yangi savol qo'shma, savol va variant "
    "matnlarini o'zgartirma va tarjima qilma. To'g'ri javoblar mening faylimda "
    "[QANDAY BELGILANGAN: masalan, * belgisi / qalin shrift / alohida javoblar ro'yxati] bilan "
    "ko'rsatilgan. Natijani aynan shu .xlsx fayl ko'rinishida qaytar."
)
AI_PROMPT_RU = (
    "Я прикладываю два файла: 1) шаблон ExamTaker (.xlsx), 2) мои готовые вопросы. Перенеси мои "
    'вопросы на лист "Savollar" шаблона, строго следуя правилам на листе "AI uchun '
    "yo'riqnoma\". Не добавляй новых вопросов, не меняй и не переводи текст вопросов и "
    "вариантов. Правильные ответы в моём файле отмечены [КАК ОТМЕЧЕНЫ: например, знаком *, "
    "жирным шрифтом, отдельным списком ответов]. Верни результат именно в виде этого .xlsx файла."
)
AI_RULES = [
    "Faqat ustoz bergan savollarni ko'chir. O'zingdan yangi savol, variant yoki javob qo'shma; "
    "savol va variant matnini o'zgartirma, qisqartirma va tarjima qilma.",
    "Manbadagi BARCHA savollarni ko'chir, birortasini ham tashlab ketma.",
    "Manbada savolning to'g'ri javobi ko'rsatilmagan bo'lsa, TAXMIN QILMA — javob ustuniga (J) "
    "faqat ? belgisini yoz.",
    "Faqat \"Savollar\" varag'iga, 2-qatordan boshlab yoz. 1-qatordagi sarlavhalarni o'zgartirma.",
    '"Ma\'lumot", "Namuna" va shu varaqni o\'zgartirma, o\'chirma; varaq nomlarini '
    "o'zgartirma, yangi varaq qo'shma.",
    "Har bir qator = 1 ta savol. Ustunlar: A = T/r (1, 2, 3...), B = Turi, C = Savol matni, "
    "D–I = Variant A–F, J = To'g'ri javob, K = Ball.",
    "Turini manbadagi savolga qarab tanla: variantli va 1 ta javob — SINGLE_CHOICE; variantli va "
    "bir nechta javob — MULTIPLE_CHOICE; to'g'ri/noto'g'ri — TRUE_FALSE; javobni student o'zi "
    "yozadi — OPEN_ENDED; kod yozish topshirig'i — PYTHON_CODE.",
    "SINGLE_CHOICE: 2–6 ta variant, aynan 1 ta to'g'ri javob harfi (masalan: B).",
    "MULTIPLE_CHOICE: 2–6 ta variant, 1 yoki bir nechta to'g'ri javob, vergul bilan "
    "(masalan: A,C).",
    "TRUE_FALSE: aynan 2 ta variant (manbadagidek, masalan: To'g'ri / Noto'g'ri) va 1 ta javob "
    "harfi.",
    "OPEN_ENDED va PYTHON_CODE: variant ustunlari (D–I) va javob ustuni (J) BO'SH qoladi; "
    "faqat savol matni va ball yoziladi.",
    "Javob ustuniga faqat harf yoz (A–F), variant matnini emas.",
    'Variant matni boshiga "A)" kabi harf yozma; bitta savol ichida variantlar takrorlanmasin.',
    "Ball: manbada ko'rsatilgan bo'lsa — o'sha (1 dan 100 gacha); ko'rsatilmagan bo'lsa: "
    "SINGLE_CHOICE 2, MULTIPLE_CHOICE 3, TRUE_FALSE 1, OPEN_ENDED 5, PYTHON_CODE 5.",
    "Bitta faylda 500 tadan ko'p savol bo'lmasin.",
    "Natijani shu .xlsx fayl ko'rinishida qaytar (CSV yoki matnli jadval emas).",
]


def _add_ai_guide_sheet(workbook) -> None:
    """Ustoz o‘zining tayyor savollarini AI yordamida shablonga ko‘chirishi uchun:
    tayyor prompt va aniq qoidalar. AI o‘zi savol yaratmaydi.

    Bu varaq import qilinmaydi.
    """
    sheet = workbook.create_sheet(AI_GUIDE_SHEET)
    title_font = Font(bold=True, size=13, color="1F4E78")
    section_fill = PatternFill("solid", fgColor="DDEBF7")
    prompt_fill = PatternFill("solid", fgColor="FFF2CC")
    wrap = Alignment(wrap_text=True, vertical="top")

    def section(title: str) -> None:
        sheet.append([title])
        cell = sheet.cell(row=sheet.max_row, column=1)
        cell.font = Font(bold=True)
        cell.fill = section_fill

    sheet.append(
        ["Tayyor savollaringizni AI (ChatGPT, Gemini, Claude) yordamida shablonga ko'chirish"]
    )
    sheet.cell(row=1, column=1).font = title_font
    sheet.append(
        [
            "1) AI'ga shu shablonni va o'zingizning savollar faylingizni (Word, PDF, Excel yoki "
            "matn) yuklang. 2) Pastdagi promptni nusxalab, to'g'ri javoblar qanday belgilanganini "
            "yozing. 3) AI qaytargan faylni tekshiring (ayniqsa to'g'ri javoblarni) va "
            "platformaga yuklang. Xato chiqsa — xato matnini AI'ga berib tuzattiring."
        ]
    )
    sheet.append([])
    section("Prompt (o'zbekcha)")
    sheet.append([AI_PROMPT_UZ])
    sheet.cell(row=sheet.max_row, column=1).fill = prompt_fill
    section("Prompt (на русском)")
    sheet.append([AI_PROMPT_RU])
    sheet.cell(row=sheet.max_row, column=1).fill = prompt_fill
    sheet.append([])
    section("AI uchun qoidalar")
    for number, rule in enumerate(AI_RULES, start=1):
        sheet.append([f"{number}. {rule}"])
    sheet.column_dimensions["A"].width = 120
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = wrap


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

    _add_ai_guide_sheet(workbook)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _text(value) -> str:
    return "" if value is None else str(value).strip()


# Rus klaviaturasida yozilgan, lotin harfiga aynan o‘xshash kirill harflari.
_CYRILLIC_LOOKALIKES = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E"})


# AI va Word/Excel "aqlli" tirnoqlarni qo‘yadi: ‘ ’ ʼ ` ´ -> '
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "ʼ": "'", "`": "'", "´": "'"})


def _norm(value) -> str:
    """Sarlavha / varaq nomi solishtirish uchun: tirnoq, probel va registr farqisiz."""
    return re.sub(r"\s+", " ", _text(value).translate(_APOSTROPHES)).casefold()


_NORM_HEADERS = [_norm(header) for header in QUESTION_HEADERS]


def _correct_letters(value) -> set[str]:
    """`A`, `a, c`, `A;C`, `AC`, `A)`, `(B)`, `C.`, kirillcha `А` — hammasi qabul qilinadi."""
    raw = _text(value).upper().translate(_CYRILLIC_LOOKALIKES)
    if not raw:
        return set()
    raw = re.sub(r"[()\[\].:]", " ", raw)  # "A)", "(B)", "C." -> harfning o‘zi
    letters: set[str] = set()
    for part in re.split(r"[,;/\s]+", raw):
        if not part:
            continue
        if len(part) > 1 and set(part) <= set(OPTION_LETTERS):
            letters.update(part)  # "AC" -> A, C
        else:
            letters.add(part)
    return letters


def _strip_option_prefixes(options_by_letter: dict[str, str]) -> dict[str, str]:
    """AI ko‘pincha `A) list`, `B. tuple` deb yozadi. Prefiks faqat HAMMA variant o‘z harfi
    bilan boshlansa olib tashlanadi — oddiy matnga tasodifan tegmaslik uchun."""
    if not options_by_letter:
        return options_by_letter
    stripped = {}
    for letter, text in options_by_letter.items():
        match = re.match(rf"^\(?{letter}\s*[).:\-]\s*(.+)$", text, flags=re.IGNORECASE)
        if match is None or not match.group(1).strip():
            return options_by_letter
        stripped[letter] = match.group(1).strip()
    return stripped


def _letters_from_option_text(value, options_by_letter: dict[str, str]) -> set[str] | None:
    """Javob harf o‘rniga variant matni bilan yozilgan bo‘lsa (`tuple, str`, `To'g'ri`).

    Har bir qism biror variant matniga aynan mos kelsagina harflarga aylantiradi, aks holda None.
    """
    by_text = {_norm(text): letter for letter, text in options_by_letter.items()}
    raw = _text(value)
    if not raw or not by_text:
        return None
    whole = by_text.get(_norm(raw))  # variant matnining o‘zida vergul bo‘lishi mumkin
    if whole is not None:
        return {whole}
    letters = set()
    for part in re.split(r"[;,\n]+", raw):
        if not part.strip():
            continue
        letter = by_text.get(_norm(part))
        if letter is None:
            return None
        letters.add(letter)
    return letters or None


def _question_type(value) -> str:
    """`single choice`, `Single-Choice`, ` SINGLE_CHOICE ` -> `SINGLE_CHOICE`."""
    return re.sub(r"[\s\-/]+", "_", _text(value).upper()).strip("_")


def _points(value):
    """Matn ko‘rinishidagi `2,5` (vergulli kasr) -> `2.5`. Raqamlar o‘zgarmaydi."""
    if isinstance(value, str):
        return value.strip().replace(",", ".")
    return value


def _sheet_by_name(workbook, name: str):
    """Varaqni nomi bo‘yicha topadi (tirnoq/registr/probel farqisiz: `Ma’lumot` ham bo‘ladi)."""
    wanted = _norm(name)
    for sheet_name in workbook.sheetnames:
        if _norm(sheet_name) == wanted:
            return workbook[sheet_name]
    return None


def _header_matches(sheet) -> bool:
    width = len(QUESTION_HEADERS)
    header = next(sheet.iter_rows(min_row=1, max_row=1, max_col=width, values_only=True), ())
    return [_norm(value) for value in header] == _NORM_HEADERS


def _questions_sheet(workbook):
    """`Savollar` varag‘i; AI uni qayta nomlagan bo‘lsa — sarlavhalari mos keladigan yagona varaq.

    `Namuna`, `Ma'lumot` va yo‘riqnoma varaqlari hech qachon import qilinmaydi.
    """
    sheet = _sheet_by_name(workbook, QUESTIONS_SHEET)
    if sheet is not None:
        if not _header_matches(sheet):
            raise QuestionXLSXError("`Savollar` varag'idagi ustun nomlari o'zgartirilgan.")
        return sheet
    skipped = {_norm(EXAMPLE_SHEET), _norm(INFO_SHEET), _norm(AI_GUIDE_SHEET)}
    candidates = [
        workbook[name]
        for name in workbook.sheetnames
        if _norm(name) not in skipped and _header_matches(workbook[name])
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise QuestionXLSXError(
        "XLSX formati noto'g'ri: `Savollar` varag'i topilmadi. "
        "Shablonni `import-template` endpointidan yuklab oling."
    )


def _info_ids(workbook) -> tuple[str, str]:
    """`Ma'lumot` varag‘idan Kurs ID va Modul ID: avval A ustunidagi yorliq bo‘yicha,
    topilmasa — shablondagi joyidan (B2 / B4)."""
    info = _sheet_by_name(workbook, INFO_SHEET)
    if info is None:
        raise QuestionXLSXError(
            "XLSX formati noto'g'ri: `Ma'lumot` varag'i (Kurs ID va Modul ID) topilmadi. "
            "Shablonni `import-template` endpointidan yuklab oling."
        )
    labelled: dict[str, str] = {}
    for row in info.iter_rows(min_row=1, max_row=50, max_col=2, values_only=True):
        label, value = (*row, None, None)[:2]
        labelled.setdefault(_norm(label), _text(value))
    course_id = labelled.get("kurs id") or _text(info["B2"].value)
    module_id = labelled.get("modul id") or _text(info["B4"].value)
    if not course_id or not module_id:
        raise QuestionXLSXError("XLSX ichida Kurs ID va Modul ID bo'lishi shart.")
    return course_id, module_id


def _parse_loaded_workbook(workbook) -> ParsedQuestionWorkbook:
    course_id, module_id = _info_ids(workbook)
    sheet = _questions_sheet(workbook)
    width = len(QUESTION_HEADERS)

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
        options_by_letter = _strip_option_prefixes(
            {
                letter: _text(value)
                for letter, value in zip(OPTION_LETTERS, option_values, strict=True)
                if _text(value)
            }
        )
        if "?" in _text(correct_value):
            # Yo‘riqnoma: manbada javob ko‘rsatilmagan bo‘lsa, AI taxmin qilmay `?` yozadi.
            if question_type in MANUAL_GRADED_TYPES:
                correct_value = None  # bu turlarda javob ustuni baribir bo‘sh bo‘lishi kerak
            else:
                row_errors.append(
                    f"{row_number}-qator: to'g'ri javob ko'rsatilmagan (?). Manbadan tekshirib, "
                    "javob harfini yozing."
                )
                continue
        correct = _correct_letters(correct_value)
        unknown_answers = correct - options_by_letter.keys()
        if unknown_answers and question_type not in MANUAL_GRADED_TYPES:
            # Javob harf emas, variant matni bilan yozilgan bo‘lishi mumkin (`tuple, str`).
            from_text = _letters_from_option_text(correct_value, options_by_letter)
            if from_text is not None:
                correct, unknown_answers = from_text, set()
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

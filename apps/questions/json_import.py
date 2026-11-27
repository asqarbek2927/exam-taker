"""Question bank uchun JSON shablon yaratish va JSON import faylini o'qish.

XLSX bilan bir xil ishlaydi: shablonda kurs/modul ID'lari, AI uchun yo'riqnoma va namuna
savollar bo'ladi; ustoz (yoki AI) faqat `questions` ro'yxatini to'ldiradi. Savollar XLSX
bilan bir xil qoidalar (`build_question_data`) orqali tekshiriladi.
"""

import json
import re

from apps.academics.models import Course, Module

from .xlsx import (
    MAX_IMPORT_ROWS,
    OPTION_LETTERS,
    ParsedQuestionRow,
    ParsedQuestionWorkbook,
    QuestionXLSXError,
    _text,
    build_question_data,
)

JSON_FORMAT = "examtaker-questions"
JSON_VERSION = 1

AI_JSON_PROMPT_UZ = (
    "Senga ikkita fayl beryapman: 1) ExamTaker JSON shabloni (.json), 2) mening tayyor "
    'savollarim. Mening savollarimni shablondagi "instructions" bo\'limidagi qoidalarga '
    "qat'iy amal qilib \"questions\" ro'yxatiga ko'chir. Yangi savol qo'shma, savol va variant "
    "matnlarini o'zgartirma va tarjima qilma. To'g'ri javoblar mening faylimda "
    "[QANDAY BELGILANGAN: masalan, * belgisi / qalin shrift / alohida javoblar ro'yxati] bilan "
    "ko'rsatilgan. Natijani aynan shu .json fayl ko'rinishida qaytar."
)
AI_JSON_PROMPT_RU = (
    "Я прикладываю два файла: 1) JSON-шаблон ExamTaker (.json), 2) мои готовые вопросы. Перенеси "
    'мои вопросы в список "questions" шаблона, строго следуя правилам в разделе "instructions". '
    "Не добавляй новых вопросов, не меняй и не переводи текст вопросов и вариантов. Правильные "
    "ответы в моём файле отмечены [КАК ОТМЕЧЕНЫ: например, знаком *, жирным шрифтом, отдельным "
    "списком ответов]. Верни результат именно в виде этого .json файла."
)
AI_JSON_RULES = [
    "Faqat ustoz bergan savollarni ko'chir. O'zingdan yangi savol, variant yoki javob qo'shma; "
    "savol va variant matnini o'zgartirma, qisqartirma va tarjima qilma.",
    "Manbadagi BARCHA savollarni ko'chir, birortasini ham tashlab ketma.",
    "Manbada savolning to'g'ri javobi ko'rsatilmagan bo'lsa, TAXMIN QILMA — \"correct\": [\"?\"] "
    "deb yoz.",
    'Savollarni faqat "questions" ro\'yxatiga yoz. "format", "version", "course", "module", '
    '"instructions" va "example_questions" ni o\'zgartirma.',
    'Har bir savol: {"type": ..., "text": ..., "options": [...], "correct": [...], '
    '"points": ...}. Namunalar "example_questions" da.',
    "type faqat quyidagilardan biri: SINGLE_CHOICE, MULTIPLE_CHOICE, TRUE_FALSE, OPEN_ENDED, "
    "PYTHON_CODE.",
    "Turini manbadagi savolga qarab tanla: variantli va 1 ta javob — SINGLE_CHOICE; variantli va "
    "bir nechta javob — MULTIPLE_CHOICE; to'g'ri/noto'g'ri — TRUE_FALSE; javobni student o'zi "
    "yozadi — OPEN_ENDED; kod yozish topshirig'i — PYTHON_CODE.",
    '"options" — variant matnlari ro\'yxati (2–6 ta), tartibi manbadagidek. "correct" — '
    'to\'g\'ri variant harflari: 1-variant = "A", 2-variant = "B" va h.k.',
    'SINGLE_CHOICE: aynan 1 ta javob (masalan: ["B"]). MULTIPLE_CHOICE: 1 yoki bir nechta '
    '(masalan: ["A", "C"]). TRUE_FALSE: aynan 2 ta variant va 1 ta javob.',
    'OPEN_ENDED va PYTHON_CODE: "options": [] va "correct": [].',
    'Variant matni boshiga "A)" kabi harf yozma; bitta savol ichida variantlar takrorlanmasin.',
    "\"points\": manbada ko'rsatilgan bo'lsa — o'sha (1 dan 100 gacha); ko'rsatilmagan bo'lsa: "
    "SINGLE_CHOICE 2, MULTIPLE_CHOICE 3, TRUE_FALSE 1, OPEN_ENDED 5, PYTHON_CODE 5.",
    "Bitta faylda 500 tadan ko'p savol bo'lmasin.",
    "Natijani to'g'ri JSON fayl ko'rinishida qaytar: izohlarsiz, ``` belgilarisiz.",
]

EXAMPLE_QUESTIONS = [
    {
        "type": "SINGLE_CHOICE",
        "text": "Kuchli parol qaysi javobda to'g'ri ko'rsatilgan?",
        "options": ["12345678", "Azizbek2005", "T7#mQ2!zLp9@", "password"],
        "correct": ["C"],
        "points": 2,
    },
    {
        "type": "MULTIPLE_CHOICE",
        "text": "Qaysilari phishing xabarining belgilaridir?",
        "options": [
            "Shoshilinch havolani bosish talabi",
            "Shubhali yoki xato yozilgan domen",
            "Parolni yuborishni so'rash",
            "Oldindan kelishilgan rasmiy xabar",
        ],
        "correct": ["A", "B", "C"],
        "points": 3,
    },
    {
        "type": "TRUE_FALSE",
        "text": "HTTPS internet orqali yuborilayotgan ma'lumotlarni shifrlaydi.",
        "options": ["To'g'ri", "Noto'g'ri"],
        "correct": ["A"],
        "points": 1,
    },
    {
        "type": "OPEN_ENDED",
        "text": "Ikki faktorli autentifikatsiya nima va u nima uchun kerak?",
        "options": [],
        "correct": [],
        "points": 5,
    },
    {
        "type": "PYTHON_CODE",
        "text": "Ikki sonni qo'shib natijani chiqaradigan Python funksiyasini yozing.",
        "options": [],
        "correct": [],
        "points": 5,
    },
]


def build_question_import_json_template(*, course: Course, module: Module) -> bytes:
    template = {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "course": {"id": str(course.id), "name": course.name},
        "module": {"id": str(module.id), "title": module.title},
        "instructions": {
            "steps_uz": (
                "1) AI'ga shu shablonni va o'zingizning savollar faylingizni yuklang. "
                "2) prompt_uz ni nusxalab, to'g'ri javoblar qanday belgilanganini yozing. "
                "3) AI qaytargan .json faylni tekshiring va platformaga yuklang. "
                "Yoki savollarni o'zingiz \"questions\" ro'yxatiga yozing."
            ),
            "prompt_uz": AI_JSON_PROMPT_UZ,
            "prompt_ru": AI_JSON_PROMPT_RU,
            "rules": AI_JSON_RULES,
        },
        "example_questions": EXAMPLE_QUESTIONS,
        "questions": [],
    }
    return json.dumps(template, ensure_ascii=False, indent=2).encode("utf-8")


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------
def _first(item: dict, *keys):
    """AI kalit nomini biroz boshqacha yozishi mumkin (`question`, `answer`, `ball` ...)."""
    lowered = {str(key).strip().casefold(): value for key, value in item.items()}
    for key in keys:
        if key in lowered:
            return lowered[key]
    return None


def _load_json(raw: bytes):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise QuestionXLSXError("JSON fayl UTF-8 kodlashda bo'lishi kerak.") from exc
    text = text.strip()
    # AI ko‘pincha natijani ```json ... ``` ichiga o‘rab beradi.
    fenced = re.fullmatch(r"```[a-zA-Z]*\s*(.*?)\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise QuestionXLSXError(
            f"JSON formati noto'g'ri: {exc.msg} ({exc.lineno}-qator, {exc.colno}-ustun)."
        ) from exc
    except (RecursionError, ValueError) as exc:
        # Juda chuqur ichma-ich ro‘yxatlar yoki 4300+ xonali sonlar — 500 emas, aniq xato.
        raise QuestionXLSXError(
            "JSON formati noto'g'ri: fayl juda chuqur yoki juda katta qiymatlarga ega."
        ) from exc


def _context_ids(data: dict) -> tuple[str, str]:
    course, module = data.get("course"), data.get("module")
    course_id = _text(course.get("id") if isinstance(course, dict) else data.get("course_id"))
    module_id = _text(module.get("id") if isinstance(module, dict) else data.get("module_id"))
    if not course_id or not module_id:
        raise QuestionXLSXError(
            "JSON ichida course.id va module.id bo'lishi shart. Shablonni "
            "`import-template-json` endpointidan yuklab oling."
        )
    return course_id, module_id


def _options_and_correct(label: str, options, correct) -> tuple[dict[str, str], object]:
    """`options`: ["matn", ...] | [{"text":..., "is_correct":...}, ...] | {"A": "matn", ...}."""
    if options is None:
        options = []
    if isinstance(options, dict):  # {"A": "list", "B": "tuple"}
        options = [options[key] for key in sorted(options, key=lambda key: str(key).upper())]
    if not isinstance(options, list):
        raise ValueError(f"{label}: \"options\" ro'yxat bo'lishi kerak.")
    if len(options) > len(OPTION_LETTERS):
        raise ValueError(f"{label}: ko'pi bilan {len(OPTION_LETTERS)} ta variant bo'lishi mumkin.")
    texts, flagged = [], []
    for index, option in enumerate(options):
        if isinstance(option, dict):
            texts.append(_text(_first(option, "text", "matn", "option", "variant")))
            if _first(option, "is_correct", "correct") is True:
                flagged.append(OPTION_LETTERS[index])
        else:
            texts.append(_text(option))
    by_letter = {letter: text for letter, text in zip(OPTION_LETTERS, texts, strict=False) if text}
    if correct is None and flagged:
        correct = flagged
    if isinstance(correct, list):
        correct = ",".join(_text(value) for value in correct)
    return by_letter, correct


def parse_question_import_json(file_obj) -> ParsedQuestionWorkbook:
    data = _load_json(file_obj.read())
    if not isinstance(data, dict):
        raise QuestionXLSXError(
            "JSON formati noto'g'ri: fayl shablondagidek obyekt ({...}) bo'lishi kerak. "
            "Shablonni `import-template-json` endpointidan yuklab oling."
        )
    course_id, module_id = _context_ids(data)
    items = data.get("questions")
    if not isinstance(items, list):
        raise QuestionXLSXError("JSON ichida \"questions\" ro'yxati bo'lishi kerak.")
    items = [item for item in items if item not in (None, {}, "")]
    if len(items) > MAX_IMPORT_ROWS:
        raise QuestionXLSXError(
            f"Bitta faylda ko'pi bilan {MAX_IMPORT_ROWS} ta savol bo'lishi mumkin."
        )

    questions: list[ParsedQuestionRow] = []
    errors: list[str] = []
    for number, item in enumerate(items, start=1):
        label = f"{number}-savol"
        if not isinstance(item, dict):
            errors.append(f"{label}: savol obyekt ({{...}}) bo'lishi kerak.")
            continue
        try:
            options_by_letter, correct = _options_and_correct(
                label,
                _first(item, "options", "variants", "variantlar"),
                _first(item, "correct", "answer", "answers", "correct_answers", "javob"),
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        question, error = build_question_data(
            label=label,
            question_type=_first(item, "type", "turi"),
            question_text=_first(item, "text", "question", "savol"),
            options_by_letter=options_by_letter,
            correct_value=correct,
            points=_first(item, "points", "ball", "default_points"),
        )
        if error is not None:
            errors.append(error)
            continue
        questions.append(ParsedQuestionRow(row=number, data=question))

    if errors:
        raise QuestionXLSXError(errors)
    if not questions:
        raise QuestionXLSXError('"questions" ro\'yxatida import qilinadigan savol topilmadi.')
    return ParsedQuestionWorkbook(course_id=course_id, module_id=module_id, questions=questions)

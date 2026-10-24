"""Savol turlari bo‘yicha option qoidalari (TZ 8.3) — serializer va service uchun yagona manba."""

from collections.abc import Sequence

from .choices import QuestionType

MIN_CHOICE_OPTIONS = 2


def validate_options(question_type: str, options: Sequence[dict]) -> list[str]:
    """Xatolar ro‘yxatini qaytaradi (bo‘sh ro‘yxat — hammasi to‘g‘ri).

    `options` elementi: ``{"text": str, "is_correct": bool}``.
    """
    errors: list[str] = []
    total = len(options)
    correct = sum(1 for option in options if option.get("is_correct"))

    if question_type == QuestionType.OPEN_ENDED:
        if total:
            errors.append("OPEN_ENDED savolda optionlar bo‘lmasligi kerak.")
        return errors

    texts = [str(option.get("text", "")).strip().casefold() for option in options]
    if any(not text for text in texts):
        errors.append("Option matni bo‘sh bo‘lishi mumkin emas.")
    if len(set(texts)) != len(texts):
        errors.append("Optionlar matni takrorlanmasligi kerak.")

    if question_type == QuestionType.TRUE_FALSE:
        if total != 2:
            errors.append("TRUE_FALSE savolda aynan 2 ta option bo‘lishi kerak.")
        if correct != 1:
            errors.append("TRUE_FALSE savolda aynan 1 ta to‘g‘ri option bo‘lishi kerak.")
    elif question_type == QuestionType.SINGLE_CHOICE:
        if total < MIN_CHOICE_OPTIONS:
            errors.append(f"SINGLE_CHOICE savolda kamida {MIN_CHOICE_OPTIONS} ta option kerak.")
        if correct != 1:
            errors.append("SINGLE_CHOICE savolda aynan 1 ta to‘g‘ri option bo‘lishi kerak.")
    elif question_type == QuestionType.MULTIPLE_CHOICE:
        if total < MIN_CHOICE_OPTIONS:
            errors.append(f"MULTIPLE_CHOICE savolda kamida {MIN_CHOICE_OPTIONS} ta option kerak.")
        if correct < 1:
            errors.append("MULTIPLE_CHOICE savolda kamida 1 ta to‘g‘ri option bo‘lishi kerak.")
    else:
        errors.append("Noma’lum savol turi.")
    return errors

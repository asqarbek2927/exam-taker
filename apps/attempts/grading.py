"""Auto-grading sof funksiyalari (DB ga tegmaydi) — oson test qilinadi (TZ 11.5)."""

from decimal import ROUND_HALF_UP, Decimal

from apps.questions.choices import QuestionType

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Ballarni 2 xonagacha yaxlitlaydi (ROUND_HALF_UP)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def grade_choice_answer(
    question_type: str,
    points: Decimal,
    correct_ids: set,
    selected_ids: set,
    all_option_ids: set | None = None,
) -> tuple[bool, Decimal]:
    """Tanlovli savolni baholaydi. Qaytaradi: `(is_correct, points_awarded)`.

    * SINGLE_CHOICE / TRUE_FALSE: aynan to‘g‘ri option tanlangan bo‘lsa — to‘liq ball, aks holda 0.
    * MULTIPLE_CHOICE (partial):
        raw = (to‘g‘ri tanlangan − noto‘g‘ri tanlangan) / jami to‘g‘ri optionlar
        ball = points * min(1, max(0, raw))
      Hamma optionni belgilab to‘liq ball olib bo‘lmaydi.
    """
    is_exact = selected_ids == correct_ids and bool(correct_ids)

    if question_type == QuestionType.MULTIPLE_CHOICE:
        if not selected_ids or not correct_ids:
            return False, Decimal("0.00")
        option_ids = all_option_ids or (correct_ids | selected_ids)
        incorrect_ids = option_ids - correct_ids
        right_factor = Decimal(len(selected_ids & correct_ids)) / Decimal(len(correct_ids))
        wrong_factor = (
            Decimal(len(selected_ids & incorrect_ids)) / Decimal(len(incorrect_ids))
            if incorrect_ids
            else Decimal(0)
        )
        raw = right_factor - wrong_factor
        factor = min(Decimal(1), max(Decimal(0), raw))
        return is_exact, money(points * factor)

    # SINGLE_CHOICE, TRUE_FALSE
    if is_exact and len(selected_ids) == 1:
        return True, money(points)
    return False, Decimal("0.00")


def passed(score: Decimal, total: Decimal, passing_percent: Decimal) -> bool:
    """`score/total*100 >= passing_percent` — bo‘lishsiz (yaxlitlash xatosisiz) taqqoslanadi."""
    return score * 100 >= passing_percent * total


def percentage(score: Decimal, total: Decimal) -> Decimal:
    return money(score * 100 / total)

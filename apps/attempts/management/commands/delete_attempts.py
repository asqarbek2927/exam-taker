"""Test (sinov) uchun topshirilgan attempt'larni natijalardan o'chirish.

Sukut bo'yicha FAQAT ko'rsatadi (dry-run). Haqiqatan o'chirish uchun `--yes`.

Misollar:
    # "Python" imtihonidagi bugungi attempt'larni ko'rish
    manage.py delete_attempts --exam-title Python --since 2026-11-27
    # test_student ning shu imtihondagi attempt'larini o'chirish
    manage.py delete_attempts --exam-title Python --student test_student --yes
    # aniq attempt ID'lar bo'yicha
    manage.py delete_attempts --attempt <uuid> --attempt <uuid> --yes
"""

import logging
from datetime import date, datetime, time

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from apps.attempts.models import ExamAttempt
from apps.attempts.services import delete_attempts

security_logger = logging.getLogger("examtaker.security")


def _day(value: str, *, end: bool) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Sana YYYY-MM-DD formatida bo'lishi kerak: {value}") from exc
    return timezone.make_aware(datetime.combine(parsed, time.max if end else time.min))


class Command(BaseCommand):
    help = (
        "Attempt'larni (javoblari bilan) natijalardan o'chiradi. Sukut bo'yicha faqat "
        "ro'yxatni ko'rsatadi; o'chirish uchun --yes qo'shing."
    )

    def add_arguments(self, parser):
        parser.add_argument("--attempt", action="append", default=[], help="Attempt ID (UUID)")
        parser.add_argument(
            "--student", action="append", default=[], help="Student username yoki email"
        )
        parser.add_argument(
            "--assignment", action="append", default=[], help="E'lon (assignment) ID"
        )
        parser.add_argument(
            "--exam-title", help="Imtihon nomida shu matn bor (katta-kichik farqsiz)"
        )
        parser.add_argument("--since", help="Shu sanadan boshlab boshlangan (YYYY-MM-DD)")
        parser.add_argument("--until", help="Shu sanagacha boshlangan (YYYY-MM-DD)")
        parser.add_argument(
            "--max", type=int, default=50, help="Bir martada ko'pi bilan nechta (sukut: 50)"
        )
        parser.add_argument("--yes", action="store_true", help="Haqiqatan o'chirish")

    def handle(self, *args, **options):
        filters = Q()
        if options["attempt"]:
            filters &= Q(pk__in=options["attempt"])
        if options["student"]:
            who = Q()
            for value in options["student"]:
                who |= Q(student__username__iexact=value) | Q(student__email__iexact=value)
            filters &= who
        if options["assignment"]:
            filters &= Q(assignment_id__in=options["assignment"])
        if options["exam_title"]:
            filters &= Q(assignment__exam__title__icontains=options["exam_title"])
        if options["since"]:
            filters &= Q(started_at__gte=_day(options["since"], end=False))
        if options["until"]:
            filters &= Q(started_at__lte=_day(options["until"], end=True))
        if not filters:
            raise CommandError(
                "Kamida bitta filtr bering: --attempt, --student, --assignment, --exam-title, "
                "--since yoki --until. Hamma attempt'ni bir buyruq bilan o'chirib bo'lmaydi."
            )

        try:
            attempts = list(
                ExamAttempt.objects.filter(filters)
                .select_related("student", "assignment__exam")
                .order_by("started_at")
            )
        except (ValidationError, ValueError) as exc:  # masalan, noto'g'ri UUID
            raise CommandError(f"Filtr noto'g'ri: {exc}") from exc

        if not attempts:
            self.stdout.write("Mos attempt topilmadi.")
            return

        self.stdout.write(f"Topildi: {len(attempts)} ta attempt\n")
        for attempt in attempts:
            started = timezone.localtime(attempt.started_at).strftime("%Y-%m-%d %H:%M")
            score = "-" if attempt.score is None else attempt.score
            self.stdout.write(
                f"  {attempt.pk}  {attempt.student.username:<20} "
                f"{attempt.student.full_name[:25]:<25} {attempt.assignment.exam.title[:30]:<30} "
                f"#{attempt.attempt_number} {attempt.status:<16} ball={score}  {started}"
            )

        if len(attempts) > options["max"]:
            raise CommandError(
                f"{len(attempts)} ta attempt — bu --max ({options['max']}) dan ko'p. Filtrni "
                "aniqlashtiring yoki ataylab bo'lsa --max ni oshiring."
            )
        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nHech narsa o'chirilmadi (ko'rish rejimi). Ro'yxat to'g'ri bo'lsa, "
                    "xuddi shu buyruqqa --yes qo'shing."
                )
            )
            return

        deleted = delete_attempts(ExamAttempt.objects.filter(pk__in=[a.pk for a in attempts]))
        security_logger.warning(
            "attempts_deleted count=%s ids=%s", deleted, ",".join(str(a.pk) for a in attempts)
        )
        self.stdout.write(self.style.SUCCESS(f"\nO'chirildi: {deleted} ta attempt."))

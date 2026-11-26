"""Legacy (snapshotdan oldingi) attempt ma'lumotlari qolgan-qolmaganini tekshiradi.

Faqat O'QIYDI — hech narsani o'zgartirmaydi. Legacy fallback kodini (`exam_question`
ga bog'langan javoblar) olib tashlashdan oldin production'da ishga tushiring::

    docker compose -f docker-compose.prod.yml exec web python manage.py check_legacy_attempts

Hamma sonlar 0 bo'lsa, legacy kodni olib tashlash xavfsiz.
"""

from django.core.management.base import BaseCommand

from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt, StudentAnswer, StudentAnswerOption


def legacy_counts() -> dict[str, int]:
    legacy_attempts = ExamAttempt.objects.filter(delivery_questions__isnull=True).distinct()
    return {
        "attempts_without_snapshot": legacy_attempts.count(),
        "in_progress_attempts_without_snapshot": legacy_attempts.filter(
            status=AttemptStatus.IN_PROGRESS
        ).count(),
        "answers_linked_to_exam_question": StudentAnswer.objects.filter(
            attempt_question__isnull=True
        ).count(),
        "selected_options_linked_to_bank_option": StudentAnswerOption.objects.filter(
            attempt_option__isnull=True
        ).count(),
        "attempts_without_assignment_snapshot": ExamAttempt.objects.filter(
            assignment__snapshot__isnull=True
        ).count(),
    }


class Command(BaseCommand):
    help = "Legacy (snapshotdan oldingi) attempt ma'lumotlarini sanaydi. Faqat o'qiydi."

    def handle(self, *args, **options):
        counts = legacy_counts()
        for name, value in counts.items():
            self.stdout.write(f"{name}: {value}")
        if any(counts.values()):
            self.stdout.write(
                self.style.WARNING(
                    "Legacy ma'lumot bor — legacy kodni olib tashlash XAVFSIZ EMAS. "
                    "Avval ma'lumotni ko'chiruvchi migratsiya kerak."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Legacy ma'lumot yo'q — olib tashlash xavfsiz."))

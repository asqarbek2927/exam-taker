from django.core.management.base import BaseCommand

from apps.attempts.services import finalize_expired_attempts


class Command(BaseCommand):
    help = (
        "Muddati o‘tgan (deadline + grace) faol attemptlarni saqlangan javoblar bilan avtomatik "
        "yakunlaydi. Cron/docker orqali har 1–5 daqiqada ishga tushiring."
    )

    def handle(self, *args, **options):
        count = finalize_expired_attempts()
        self.stdout.write(self.style.SUCCESS(f"Yopilgan attemptlar: {count}"))

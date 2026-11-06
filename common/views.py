"""Umumiy HTTP viewlar: healthcheck hamda API 404/500 handlerlari."""

import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views import defaults
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health_live(request):
    """Process ishlayotganini bildiradi; tashqi servislarga murojaat qilmaydi."""
    return JsonResponse({"status": "ok"})


@require_GET
def health_ready(request):
    """Web process DB va shared cache bilan ishlashga tayyorligini tekshiradi."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache.set("health:ready", "ok", timeout=30)
        if cache.get("health:ready") != "ok":
            raise RuntimeError("Cache read/write check failed")
    except Exception:
        logger.exception("Readiness check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def _is_api(request) -> bool:
    return request.path.startswith("/api/")


def not_found(request, exception, template_name="404.html"):
    if _is_api(request):
        return JsonResponse(
            {"status_code": 404, "error": "Not Found", "message": "Resurs topilmadi."},
            status=404,
        )
    return defaults.page_not_found(request, exception, template_name=template_name)


def server_error(request, template_name="500.html"):
    if _is_api(request):
        return JsonResponse(
            {
                "status_code": 500,
                "error": "Internal Server Error",
                "message": "Serverda kutilmagan xatolik yuz berdi.",
            },
            status=500,
        )
    return defaults.server_error(request, template_name=template_name)

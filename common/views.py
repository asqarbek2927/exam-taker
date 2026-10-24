"""URL resolver darajasidagi 404/500 uchun JSON handlerlar (faqat `/api/` yo‘llari)."""

from django.http import JsonResponse
from django.views import defaults


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

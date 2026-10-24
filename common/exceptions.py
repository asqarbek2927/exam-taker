"""Yagona xatolik formati (TZ 4.4).

Business qoida buzilishi / boshqa xatolar::

    {"status_code": 400, "error": "Bad Request", "message": "..."}

Validation (422)::

    {"status_code": 422, "message": "Validation failed", "errors": {...}}
"""

from http import HTTPStatus

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db.models import ProtectedError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    UnsupportedMediaType,
    ValidationError,
)
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken


class BusinessRuleError(APIException):
    """Business qoidasi buzildi (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Business qoidasi buzildi."
    default_code = "business_rule_violation"


class AccessDeniedError(PermissionDenied):
    """Rol to‘g‘ri, lekin shu resursga ruxsat yo‘q (403) — xabari saqlanadi."""

    default_detail = "Bu resursga kirish huquqingiz yo‘q."


class ConflictError(APIException):
    """Holat to‘qnashuvi: unique, limit, himoyalangan bog‘lanish va h.k. (409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "So‘rov joriy holat bilan to‘qnashadi."
    default_code = "conflict"


def _to_plain(detail):
    """`ErrorDetail` larni oddiy `str` ga aylantiradi, tuzilmani saqlaydi."""
    if isinstance(detail, dict):
        return {key: _to_plain(value) for key, value in detail.items()}
    if isinstance(detail, (list, tuple)):
        return [_to_plain(item) for item in detail]
    return str(detail)


def _message(exc: APIException) -> str:
    if isinstance(exc, InvalidToken):
        return "Token yaroqsiz yoki muddati tugagan."
    if isinstance(exc, NotAuthenticated):
        return "Autentifikatsiya talab qilinadi."
    if isinstance(exc, AccessDeniedError):
        return str(exc.detail)
    if isinstance(exc, PermissionDenied):
        return "Bu amalni bajarish uchun ruxsat yo‘q."
    if isinstance(exc, NotFound):
        return "Resurs topilmadi."
    if isinstance(exc, MethodNotAllowed):
        return "Bu HTTP metodi ushbu manzil uchun qo‘llab-quvvatlanmaydi."
    if isinstance(exc, UnsupportedMediaType):
        return "Qo‘llab-quvvatlanmaydigan Content-Type. `application/json` yuboring."
    if isinstance(exc, ParseError):
        return "So‘rov tanasi noto‘g‘ri formatda (JSON xato)."
    if isinstance(exc, Throttled):
        wait = int(exc.wait) if exc.wait is not None else None
        if wait:
            return f"So‘rovlar soni oshib ketdi. {wait} soniyadan keyin urinib ko‘ring."
        return "So‘rovlar soni oshib ketdi. Keyinroq urinib ko‘ring."

    detail = exc.detail
    if isinstance(detail, dict):
        detail = detail.get("detail", next(iter(detail.values()), ""))
    if isinstance(detail, (list, tuple)):
        detail = detail[0] if detail else ""
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = PermissionDenied()
    elif isinstance(exc, ProtectedError):
        exc = ConflictError(
            "Obyekt boshqa ma’lumotlar bilan bog‘langan, shu sababli o‘chirib bo‘lmaydi."
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # 500 — Django o‘zi qayta ishlaydi (log + 500)

    if isinstance(exc, ValidationError):
        errors = _to_plain(exc.detail)
        if not isinstance(errors, dict):
            errors = {"non_field_errors": errors if isinstance(errors, list) else [errors]}
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        response.data = {
            "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "message": "Validation failed",
            "errors": errors,
        }
        return response

    code = response.status_code
    response.data = {
        "status_code": code,
        "error": HTTPStatus(code).phrase,
        "message": _message(exc) if isinstance(exc, APIException) else str(exc),
    }
    return response


__all__ = ["AccessDeniedError", "BusinessRuleError", "ConflictError", "api_exception_handler"]

"""Login uchun throttling.

Maktab/akademiya tarmog‘ida ko‘p foydalanuvchi bitta (NAT) IP dan kiradi, shuning
uchun oddiy IP-limit imtihon boshlanishida haqiqiy studentlarni bloklab qo‘yadi.
Shu sababli:

* ``LoginRateThrottle``   — (IP + username/email) juftligi bo‘yicha qat’iy limit
  (parol terish hujumiga qarshi);
* ``LoginIPRateThrottle`` — faqat IP bo‘yicha keng limit
  (ommaviy hujumdan himoya).
"""

import hashlib

from rest_framework.exceptions import ParseError
from rest_framework.throttling import SimpleRateThrottle


def _identifier_from(request) -> str:
    try:
        data = request.data
    except ParseError:
        return ""
    if not hasattr(data, "get"):
        return ""
    value = (
        data.get("username_or_email")
        or data.get("usernameOrEmail")
        or data.get("username")
        or data.get("email")
        or ""
    )
    return str(value).strip().lower()


class LoginRateThrottle(SimpleRateThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        identifier_hash = hashlib.sha256(_identifier_from(request).encode()).hexdigest()[:16]
        ident = f"{self.get_ident(request)}:{identifier_hash}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginIPRateThrottle(SimpleRateThrottle):
    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


# --------------------------------------------------------------------------
# Refresh token
# --------------------------------------------------------------------------
# Bitta sinf (NAT IP) dagi hamma studentning access tokeni bir daqiqada tugaydi va
# ular bir vaqtda refresh qiladi. Shuning uchun refresh uchun asosiy limit — user
# bo‘yicha, IP limiti esa faqat ommaviy hujumga qarshi keng chegara.
def _refresh_identifier_from(request) -> str:
    try:
        data = request.data
    except ParseError:
        return ""
    raw = data.get("refresh_token") if hasattr(data, "get") else None
    if not isinstance(raw, str) or not raw:
        return ""
    from rest_framework_simplejwt.exceptions import TokenBackendError
    from rest_framework_simplejwt.settings import api_settings as jwt_settings
    from rest_framework_simplejwt.state import token_backend

    try:
        # Faqat throttle kaliti uchun: imzo bu yerda tekshirilmaydi (serializer tekshiradi).
        payload = token_backend.decode(raw, verify=False)
        user_id = payload.get(jwt_settings.USER_ID_CLAIM)
    except TokenBackendError:  # buzuq token: hash bo‘yicha cheklanadi
        user_id = None
    if user_id:
        return f"user:{user_id}"
    return "token:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


class RefreshUserRateThrottle(SimpleRateThrottle):
    scope = "refresh"

    def get_cache_key(self, request, view):
        ident = _refresh_identifier_from(request) or f"ip:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RefreshIPRateThrottle(SimpleRateThrottle):
    scope = "refresh_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}

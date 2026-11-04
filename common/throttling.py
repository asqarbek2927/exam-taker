"""Login uchun throttling.

Maktab/akademiya tarmog‘ida ko‘p foydalanuvchi bitta (NAT) IP dan kiradi, shuning
uchun oddiy IP-limit imtihon boshlanishida haqiqiy studentlarni bloklab qo‘yadi.
Shu sababli:

* ``LoginRateThrottle``   — (IP + username) juftligi bo‘yicha qat’iy limit
  (parol terish hujumiga qarshi);
* ``LoginIPRateThrottle`` — faqat IP bo‘yicha keng limit
  (ommaviy hujumdan himoya).
"""

import hashlib

from rest_framework.exceptions import ParseError
from rest_framework.throttling import SimpleRateThrottle


def _username_from(request) -> str:
    try:
        data = request.data
    except ParseError:
        return ""
    if not hasattr(data, "get"):
        return ""
    return str(data.get("username", "")).strip().lower()


class LoginRateThrottle(SimpleRateThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        username_hash = hashlib.sha256(_username_from(request).encode()).hexdigest()[:16]
        ident = f"{self.get_ident(request)}:{username_hash}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginIPRateThrottle(SimpleRateThrottle):
    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}

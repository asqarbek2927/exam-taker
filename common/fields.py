from rest_framework import serializers


class UUIDRelatedField(serializers.PrimaryKeyRelatedField):
    """`PrimaryKeyRelatedField` — o‘zbekcha xabarlar bilan."""

    default_error_messages = {
        "required": "Bu maydon majburiy.",
        "does_not_exist": "Obyekt topilmadi.",
        "incorrect_type": "Noto‘g‘ri qiymat turi. UUID kutilgan.",
        "null": "Bu maydon bo‘sh bo‘lishi mumkin emas.",
    }

import uuid

from rest_framework.exceptions import ValidationError


def parse_uuid_list(query_params, param: str) -> list[uuid.UUID]:
    """`?ids=a&ids=b` va `?ids=a,b` ko‘rinishlarini qo‘llab-quvvatlaydi (TZ 4.3)."""
    values: list[uuid.UUID] = []
    for raw in query_params.getlist(param):
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = uuid.UUID(part)
            except ValueError as exc:
                raise ValidationError({param: [f"‘{part}’ — noto‘g‘ri UUID."]}) from exc
            if value not in values:
                values.append(value)
    return values

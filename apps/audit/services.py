from typing import Any

from .models import AuditLog

SENSITIVE_KEY_PARTS = frozenset(
    {
        "password",
        "token",
        "secret",
        "answer",
        "correct",
        "feedback",
        "authorization",
    }
)


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_metadata(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_metadata(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def record_audit(
    *, actor, action: str, entity_type: str, entity_id, metadata: dict | None = None
) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=_safe_metadata(metadata or {}),
    )

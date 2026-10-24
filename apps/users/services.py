"""Yozish (write) business logic — users."""

from django.db import IntegrityError, transaction
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from common.exceptions import BusinessRuleError, ConflictError

from .choices import UserRole, UserStatus
from .models import User

EMAIL_TAKEN = "Bu email allaqachon ro‘yxatdan o‘tgan."


def revoke_all_tokens(user: User) -> None:
    """Userning barcha refresh tokenlarini bekor qiladi (blacklist)."""
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def create_user(
    *, full_name: str, email: str, password: str, role: str, avatar_url: str = ""
) -> User:
    if role not in (UserRole.TEACHER, UserRole.STUDENT):
        raise BusinessRuleError("Faqat TEACHER yoki STUDENT yaratish mumkin.")
    try:
        with transaction.atomic():
            return User.objects.create_user(
                email=email,
                password=password,
                full_name=full_name,
                role=role,
                avatar_url=avatar_url,
            )
    except IntegrityError as exc:
        raise ConflictError(EMAIL_TAKEN) from exc


def update_user(user: User, **fields) -> User:
    allowed = {"full_name", "email", "avatar_url"}
    changed = [name for name in fields if name in allowed]
    for name in changed:
        setattr(user, name, fields[name])
    if not changed:
        return user
    try:
        with transaction.atomic():
            user.save(update_fields=[*changed, "updated_at"])
    except IntegrityError as exc:
        raise ConflictError(EMAIL_TAKEN) from exc
    return user


@transaction.atomic
def deactivate_user(*, user: User, acting_user: User) -> User:
    if user.pk == acting_user.pk:
        raise BusinessRuleError("O‘zingizni nofaol qila olmaysiz.")
    if user.status != UserStatus.INACTIVE:
        user.status = UserStatus.INACTIVE
        user.save(update_fields=["status", "updated_at"])
    revoke_all_tokens(user)
    return user


def activate_user(*, user: User) -> User:
    if user.status != UserStatus.ACTIVE:
        user.status = UserStatus.ACTIVE
        user.save(update_fields=["status", "updated_at"])
    return user


@transaction.atomic
def set_user_password(*, user: User, password: str) -> None:
    user.set_password(password)
    user.save(update_fields=["password", "updated_at"])
    revoke_all_tokens(user)

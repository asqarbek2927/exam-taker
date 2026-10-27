"""Yozish (write) business logic — users."""

import secrets

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from common.exceptions import BusinessRuleError, ConflictError

from .choices import UserRole, UserStatus
from .models import User

EMAIL_TAKEN = "Bu email allaqachon ro‘yxatdan o‘tgan."
PASSWORD_LENGTH = 16
PASSWORD_LOWERCASE = "abcdefghijkmnopqrstuvwxyz"
PASSWORD_UPPERCASE = "ABCDEFGHJKLMNPQRSTUVWXYZ"
PASSWORD_DIGITS = "23456789"
PASSWORD_SYMBOLS = "!@#$%&*+-_?"


def generate_random_password(length: int = PASSWORD_LENGTH) -> str:
    """Har bir belgilar guruhidan foydalanadigan kriptografik random parol."""
    if length < 8:
        raise ValueError("Random parol uzunligi kamida 8 bo‘lishi kerak.")
    alphabet = PASSWORD_LOWERCASE + PASSWORD_UPPERCASE + PASSWORD_DIGITS + PASSWORD_SYMBOLS
    characters = [
        secrets.choice(PASSWORD_LOWERCASE),
        secrets.choice(PASSWORD_UPPERCASE),
        secrets.choice(PASSWORD_DIGITS),
        secrets.choice(PASSWORD_SYMBOLS),
        *(secrets.choice(alphabet) for _ in range(length - 4)),
    ]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def _generate_valid_password(user: User) -> str:
    """Amaldagi Django password validatorlaridan o‘tadigan random parol yaratadi."""
    for _ in range(10):
        password = generate_random_password()
        try:
            password_validation.validate_password(password, user=user)
        except DjangoValidationError:
            continue
        return password
    raise RuntimeError("Validatorlardan o‘tadigan random parol yaratib bo‘lmadi.")


def revoke_all_tokens(user: User) -> None:
    """Userning barcha refresh tokenlarini bekor qiladi (blacklist)."""
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def create_user(
    *,
    full_name: str,
    email: str,
    role: str,
    password: str | None = None,
    avatar_url: str | None = "",
) -> tuple[User, str | None]:
    if role not in (UserRole.TEACHER, UserRole.STUDENT):
        raise BusinessRuleError("Faqat TEACHER yoki STUDENT yaratish mumkin.")
    generated_password = None
    if password is None:
        probe = User(full_name=full_name, email=email, role=role)
        generated_password = _generate_valid_password(probe)
        password = generated_password
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                full_name=full_name,
                role=role,
                avatar_url=avatar_url or "",
            )
            return user, generated_password
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


def update_current_user(user: User, **fields) -> User:
    allowed = {"full_name", "phone_number", "avatar_url", "language"}
    changed = [name for name in fields if name in allowed]
    for name in changed:
        value = fields[name]
        if name == "avatar_url":
            value = value or ""
        setattr(user, name, value)
    if changed:
        user.save(update_fields=[*changed, "updated_at"])
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

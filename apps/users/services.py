"""Yozish (write) business logic — users."""

import secrets
from datetime import datetime, timedelta

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from common.exceptions import BusinessRuleError, ConflictError

from .choices import EDUCATOR_ROLES, UserRole, UserStatus
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
    phone_number: str = "",
    location: str = "",
) -> tuple[User, str | None]:
    if role not in (*EDUCATOR_ROLES, UserRole.STUDENT):
        raise BusinessRuleError("Faqat educator yoki STUDENT yaratish mumkin.")
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
                phone_number=phone_number,
                location=location,
                must_change_password=generated_password is not None,
                temporary_password_expires_at=(
                    timezone.now() + timedelta(hours=24) if generated_password else None
                ),
            )
            return user, generated_password
    except IntegrityError as exc:
        raise ConflictError(EMAIL_TAKEN) from exc


def update_current_user(user: User, **fields) -> User:
    allowed = {"full_name", "phone_number"}
    changed = [name for name in fields if name in allowed]
    for name in changed:
        value = fields[name]
        setattr(user, name, value)
    if changed:
        user.save(update_fields=[*changed, "updated_at"])
    return user


def _delete_stored_file(storage, name: str) -> None:
    if name:
        storage.delete(name)


@transaction.atomic
def replace_avatar(user: User, avatar) -> User:
    old_name = user.avatar.name
    storage = user.avatar.storage
    user.avatar = avatar
    user.avatar_url = ""
    user.save(update_fields=["avatar", "avatar_url", "updated_at"])
    if old_name and old_name != user.avatar.name:
        transaction.on_commit(lambda: _delete_stored_file(storage, old_name))
    return user


@transaction.atomic
def delete_avatar(user: User) -> None:
    old_name = user.avatar.name
    storage = user.avatar.storage
    user.avatar = ""
    user.avatar_url = ""
    user.save(update_fields=["avatar", "avatar_url", "updated_at"])
    if old_name:
        transaction.on_commit(lambda: _delete_stored_file(storage, old_name))


@transaction.atomic
def set_user_password(*, user: User, password: str) -> None:
    user.set_password(password)
    user.must_change_password = False
    user.temporary_password_expires_at = None
    user.save(
        update_fields=[
            "password",
            "must_change_password",
            "temporary_password_expires_at",
            "updated_at",
        ]
    )
    revoke_all_tokens(user)


def _record_account_audit(*, actor, action, user: User, metadata=None) -> None:
    from apps.audit.services import record_audit

    record_audit(
        actor=actor,
        action=action,
        entity_type="account",
        entity_id=user.pk,
        metadata=metadata,
    )


@transaction.atomic
def create_admin_account(*, actor, **fields) -> tuple[User, str, datetime, datetime]:
    from apps.audit.choices import AuditAction

    user, password = create_user(password=None, **fields)
    issued_at = user.temporary_password_expires_at - timedelta(hours=24)
    _record_account_audit(
        actor=actor,
        action=AuditAction.ACCOUNT_CREATED,
        user=user,
        metadata={"role": user.role, "status": user.status, "version": user.version},
    )
    return user, password, issued_at, user.temporary_password_expires_at


@transaction.atomic
def update_admin_account(*, user: User, actor, expected_version: int, **fields) -> User:
    from apps.audit.choices import AuditAction

    user = User.objects.select_for_update().get(pk=user.pk)
    if user.version != expected_version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {user.version}.")
    if user.status == UserStatus.DELETED:
        raise ConflictError("DELETED account tahrirlanmaydi.")
    changed = [
        name
        for name in fields
        if name in {"full_name", "email", "avatar", "phone_number", "location"}
    ]
    if not changed:
        return user
    old_avatar_name = user.avatar.name
    avatar_storage = user.avatar.storage
    for name in changed:
        setattr(user, name, fields[name])
    if "avatar" in changed:
        user.avatar_url = ""
    user.version += 1
    update_fields = [*changed, "version", "updated_at"]
    if "avatar" in changed:
        update_fields.append("avatar_url")
    user.save(update_fields=update_fields)
    if "avatar" in changed and old_avatar_name and old_avatar_name != user.avatar.name:
        transaction.on_commit(lambda: _delete_stored_file(avatar_storage, old_avatar_name))
    _record_account_audit(
        actor=actor,
        action=AuditAction.ACCOUNT_UPDATED,
        user=user,
        metadata={"changed_fields": changed, "version": user.version},
    )
    return user


@transaction.atomic
def set_admin_account_status(*, user: User, actor, new_status: str, expected_version: int) -> User:
    from apps.audit.choices import AuditAction

    user = User.objects.select_for_update().get(pk=user.pk)
    if user.version != expected_version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {user.version}.")
    if user.status == UserStatus.DELETED:
        raise ConflictError("DELETED account statusi o‘zgartirilmaydi.")
    if user.pk == actor.pk and new_status != UserStatus.ACTIVE:
        raise BusinessRuleError("O‘zingizni nofaol qila olmaysiz.")
    previous = user.status
    if previous == new_status:
        return user
    user.status = new_status
    user.version += 1
    user.save(update_fields=["status", "version", "updated_at"])
    if new_status == UserStatus.INACTIVE:
        revoke_all_tokens(user)
    _record_account_audit(
        actor=actor,
        action=AuditAction.ACCOUNT_STATUS_CHANGED,
        user=user,
        metadata={"from": previous, "to": new_status, "version": user.version},
    )
    return user


@transaction.atomic
def soft_delete_account(*, user: User, actor, expected_version: int) -> User:
    from apps.academics.choices import GroupStatus
    from apps.academics.models import StudyGroup
    from apps.audit.choices import AuditAction

    user = User.objects.select_for_update().get(pk=user.pk)
    if user.version != expected_version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {user.version}.")
    if user.pk == actor.pk:
        raise BusinessRuleError("O‘zingizni o‘chira olmaysiz.")
    if user.status == UserStatus.DELETED:
        return user
    if StudyGroup.objects.filter(main_teacher=user, status=GroupStatus.ACTIVE).exists():
        raise ConflictError("Teacher faol guruh egasi; avval guruhni boshqa teacherga o‘tkazing.")
    user.status = UserStatus.DELETED
    user.deleted_at = timezone.now()
    user.version += 1
    user.save(update_fields=["status", "deleted_at", "version", "updated_at"])
    revoke_all_tokens(user)
    _record_account_audit(
        actor=actor,
        action=AuditAction.ACCOUNT_DELETED,
        user=user,
        metadata={"version": user.version},
    )
    return user


@transaction.atomic
def issue_temporary_password(*, user: User, actor) -> tuple[str, datetime, datetime]:
    from apps.audit.choices import AuditAction

    user = User.objects.select_for_update().get(pk=user.pk)
    if user.status == UserStatus.DELETED:
        raise ConflictError("DELETED accountga parol berilmaydi.")
    password = _generate_valid_password(user)
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=24)
    user.set_password(password)
    user.must_change_password = True
    user.temporary_password_expires_at = expires_at
    user.version += 1
    user.save(
        update_fields=[
            "password",
            "must_change_password",
            "temporary_password_expires_at",
            "version",
            "updated_at",
        ]
    )
    revoke_all_tokens(user)
    _record_account_audit(
        actor=actor,
        action=AuditAction.TEMP_PASSWORD_ISSUED,
        user=user,
        metadata={"expires_at": expires_at.isoformat(), "version": user.version},
    )
    return password, issued_at, expires_at


@transaction.atomic
def replace_teaching_courses(
    *, user: User, actor, courses, main_courses, expected_version: int
) -> User:
    from apps.academics.choices import CourseStatus, CourseTeacherType
    from apps.academics.models import Course, CourseTeacher
    from apps.audit.choices import AuditAction

    user = User.objects.select_for_update().get(pk=user.pk)
    if user.version != expected_version:
        raise ConflictError(f"VERSION_CONFLICT: joriy version {user.version}.")
    if user.role not in EDUCATOR_ROLES or user.status == UserStatus.DELETED:
        raise BusinessRuleError("Teaching courses faqat faol educator account uchun.")
    course_ids = {course.pk for course in courses}
    main_ids = {course.pk for course in main_courses}
    if not main_ids.issubset(course_ids):
        raise BusinessRuleError("main_course_ids course_ids ichida bo‘lishi kerak.")
    if user.role == UserRole.SUPPORT_TEACHER and main_ids:
        raise BusinessRuleError("SUPPORT_TEACHER MAIN course ola olmaydi.")
    locked_courses = list(Course.objects.select_for_update().filter(pk__in=course_ids))
    if len(locked_courses) != len(course_ids):
        raise BusinessRuleError("Course topilmadi.")
    if any(course.status == CourseStatus.ARCHIVED for course in locked_courses):
        raise BusinessRuleError("Arxivlangan course biriktirilmaydi.")
    occupied = CourseTeacher.objects.filter(
        course_id__in=main_ids, type=CourseTeacherType.MAIN
    ).exclude(teacher=user)
    if occupied.exists():
        raise ConflictError("Tanlangan course'lardan birida MAIN teacher mavjud.")

    CourseTeacher.objects.filter(teacher=user).exclude(course_id__in=course_ids).delete()
    for course in locked_courses:
        teacher_type = (
            CourseTeacherType.MAIN if course.pk in main_ids else CourseTeacherType.SUPPORT
        )
        CourseTeacher.objects.update_or_create(
            course=course,
            teacher=user,
            defaults={"type": teacher_type},
        )
    user.version += 1
    user.save(update_fields=["version", "updated_at"])
    _record_account_audit(
        actor=actor,
        action=AuditAction.TEACHING_COURSES_UPDATED,
        user=user,
        metadata={
            "course_ids": [str(value) for value in sorted(course_ids)],
            "main_course_ids": [str(value) for value in sorted(main_ids)],
            "version": user.version,
        },
    )
    return user

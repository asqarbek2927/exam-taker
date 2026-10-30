from django.db import models


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    TEACHER = "TEACHER", "Teacher"
    SUPPORT_TEACHER = "SUPPORT_TEACHER", "Support Teacher"
    STUDENT = "STUDENT", "Student"


class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    DELETED = "DELETED", "Deleted"


class UserLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    UZBEK = "uz", "O‘zbekcha"
    RUSSIAN = "ru", "Русский"


class UserTheme(models.TextChoices):
    LIGHT = "light", "Light"
    DARK = "dark", "Dark"
    SYSTEM = "system", "System"


class CreatableUserRole(models.TextChoices):
    """API orqali yaratish mumkin bo‘lgan rollar (SUPER_ADMIN — faqat `createsuperuser`)."""

    TEACHER = "TEACHER", "Teacher"
    SUPPORT_TEACHER = "SUPPORT_TEACHER", "Support Teacher"
    STUDENT = "STUDENT", "Student"


EDUCATOR_ROLES = frozenset({UserRole.TEACHER, UserRole.SUPPORT_TEACHER})

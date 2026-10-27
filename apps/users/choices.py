from django.db import models


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    TEACHER = "TEACHER", "Teacher"
    STUDENT = "STUDENT", "Student"


class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class UserLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    UZBEK = "uz", "O‘zbekcha"
    RUSSIAN = "ru", "Русский"


class CreatableUserRole(models.TextChoices):
    """API orqali yaratish mumkin bo‘lgan rollar (SUPER_ADMIN — faqat `createsuperuser`)."""

    TEACHER = "TEACHER", "Teacher"
    STUDENT = "STUDENT", "Student"

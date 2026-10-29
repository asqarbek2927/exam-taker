from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from common.models import TimeStampedModel, UUIDModel

from .choices import UserLanguage, UserRole, UserStatus, UserTheme
from .managers import UserManager


class User(UUIDModel, TimeStampedModel, AbstractBaseUser, PermissionsMixin):
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)
    role = models.CharField(max_length=20, choices=UserRole.choices, db_index=True)
    avatar_url = models.URLField(max_length=500, blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True)
    phone_number = models.CharField(max_length=32, blank=True)
    language = models.CharField(
        max_length=5, choices=UserLanguage.choices, default=UserLanguage.ENGLISH
    )
    theme = models.CharField(max_length=10, choices=UserTheme.choices, default=UserTheme.SYSTEM)
    must_change_password = models.BooleanField(default=False)
    temporary_password_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=UserStatus.choices, default=UserStatus.ACTIVE, db_index=True
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        ordering = ["full_name", "email"]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    # `status` — yagona haqiqat manbai. Django/SimpleJWT `is_active` ni tekshiradi.
    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    # Django admin paneliga faqat Super Admin kiradi.
    @property
    def is_staff(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        # Django permission tizimi (admin panel) uchun role bilan sinxron.
        self.is_superuser = self.role == UserRole.SUPER_ADMIN
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and ("role" in update_fields or "email" in update_fields):
            kwargs["update_fields"] = set(update_fields) | {"is_superuser", "email"}
        super().save(*args, **kwargs)

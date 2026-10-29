from django.contrib.auth.base_user import BaseUserManager
from django.utils.text import slugify

from .choices import UserRole


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        # Login case-insensitive: email DB da lowercase saqlanadi.
        return super().get_by_natural_key(str(username).strip().lower())

    def _create_user(self, email, password, **extra_fields):
        email = self.normalize_email(email).strip().lower() if email else email
        if email and not extra_fields.get("username"):
            base = slugify(email.split("@", 1)[0]).replace("-", "_") or "user"
            candidate = base[:140]
            suffix = 1
            while self.model._default_manager.filter(username=candidate).exists():
                suffix += 1
                candidate = f"{base[: 149 - len(str(suffix))]}_{suffix}"
            extra_fields["username"] = candidate
        if not email:
            raise ValueError("Email majburiy.")
        if not extra_fields.get("full_name"):
            raise ValueError("full_name majburiy.")
        if extra_fields.get("role") not in UserRole.values:
            raise ValueError(f"role quyidagilardan biri bo‘lishi kerak: {UserRole.values}")

        user = self.model(email=email, **extra_fields)  # email lowercase — User.save() da
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["role"] = UserRole.SUPER_ADMIN
        return self._create_user(email, password, **extra_fields)

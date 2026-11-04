from django.contrib.auth.base_user import BaseUserManager

from .choices import UserRole


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        return self.get(username__iexact=str(username).strip())

    def _create_user(self, username=None, email=None, password=None, **extra_fields):
        username = str(username).strip().lower() if username else None
        email = self.normalize_email(email).strip().lower() if email else None
        if not username:
            raise ValueError("username majburiy.")
        if not extra_fields.get("full_name"):
            raise ValueError("full_name majburiy.")
        if extra_fields.get("role") not in UserRole.values:
            raise ValueError(f"role quyidagilardan biri bo‘lishi kerak: {UserRole.values}")

        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, username=None, email=None, password=None, **extra_fields):
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields["role"] = UserRole.SUPER_ADMIN
        return self._create_user(username, email, password, **extra_fields)

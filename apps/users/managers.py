from django.contrib.auth.base_user import BaseUserManager

from .choices import UserRole


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        # Login case-insensitive: email DB da lowercase saqlanadi.
        return super().get_by_natural_key(str(username).strip().lower())

    def _create_user(self, email, password, **extra_fields):
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

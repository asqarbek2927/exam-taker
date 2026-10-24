from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.users.choices import UserRole


class _RolePermission(BasePermission):
    allowed_roles: frozenset[str] = frozenset()

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user and user.is_authenticated and getattr(user, "role", None) in self.allowed_roles
        )


class IsSuperAdmin(_RolePermission):
    message = "Bu amal faqat Super Admin uchun."
    allowed_roles = frozenset({UserRole.SUPER_ADMIN})


class IsTeacher(_RolePermission):
    message = "Bu amal faqat Teacher uchun."
    allowed_roles = frozenset({UserRole.TEACHER})


class IsStudent(_RolePermission):
    message = "Bu amal faqat Student uchun."
    allowed_roles = frozenset({UserRole.STUDENT})


class IsCreatorOrSuperAdmin(BasePermission):
    """Obyektni o‘zgartirish — faqat muallifi yoki Super Admin. O‘qish — hamma.

    Muallif maydoni sukut bo‘yicha `created_by_id`; view `owner_attr` bilan almashtiradi.
    """

    message = "Buni faqat muallifi (yoki Super Admin) o‘zgartira oladi."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        owner_id = getattr(obj, getattr(view, "owner_attr", "created_by_id"))
        return user.role == UserRole.SUPER_ADMIN or owner_id == user.id

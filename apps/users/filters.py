import django_filters

from .choices import UserRole, UserStatus
from .models import User


class UserFilter(django_filters.FilterSet):
    role = django_filters.ChoiceFilter(choices=UserRole.choices)
    status = django_filters.ChoiceFilter(choices=UserStatus.choices)

    class Meta:
        model = User
        fields = ["role", "status"]


class PersonFilter(django_filters.FilterSet):
    """`/teachers` va `/students` uchun (role qat’iy belgilangan)."""

    status = django_filters.ChoiceFilter(choices=UserStatus.choices)

    class Meta:
        model = User
        fields = ["status"]

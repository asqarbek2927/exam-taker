import django_filters

from apps.academics.choices import CourseStatus, EnrollmentStatus

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


class TeacherDirectoryFilter(PersonFilter):
    course_id = django_filters.UUIDFilter(field_name="course_assignments__course_id")

    class Meta(PersonFilter.Meta):
        fields = [*PersonFilter.Meta.fields, "course_id"]


class StudentDirectoryFilter(PersonFilter):
    course_id = django_filters.UUIDFilter(method="filter_course")
    first_letter = django_filters.CharFilter(method="filter_first_letter", max_length=1)

    def filter_course(self, queryset, name, value):
        return queryset.filter(
            enrollments__course_id=value,
            enrollments__status=EnrollmentStatus.ACTIVE,
            enrollments__course__status=CourseStatus.ACTIVE,
        )

    def filter_first_letter(self, queryset, name, value):
        return queryset.filter(full_name__istartswith=value)

    class Meta(PersonFilter.Meta):
        fields = [*PersonFilter.Meta.fields, "course_id", "first_letter"]

import django_filters

from .choices import CourseStatus, EnrollmentStatus, ModuleStatus
from .models import Course, CourseTeacher, Enrollment, Module


class CourseFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=CourseStatus.choices)

    class Meta:
        model = Course
        fields = ["status"]


class CourseTeacherFilter(django_filters.FilterSet):
    type = django_filters.ChoiceFilter(choices=CourseTeacher._meta.get_field("type").choices)

    class Meta:
        model = CourseTeacher
        fields = ["type"]


class EnrollmentFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=EnrollmentStatus.choices)

    class Meta:
        model = Enrollment
        fields = ["status"]


class ModuleFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=ModuleStatus.choices)

    class Meta:
        model = Module
        fields = ["status"]

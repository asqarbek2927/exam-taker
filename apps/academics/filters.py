import django_filters

from .choices import CourseStatus, EnrollmentStatus, GroupStatus, ModuleStatus
from .models import Course, CourseTeacher, Enrollment, Module, StudyGroup


class CourseFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=CourseStatus.choices)
    teacher_id = django_filters.UUIDFilter(field_name="course_teachers__teacher_id")

    class Meta:
        model = Course
        fields = ["status", "teacher_id"]


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


class GroupDirectoryFilter(django_filters.FilterSet):
    course_id = django_filters.UUIDFilter(field_name="course_id")
    status = django_filters.ChoiceFilter(choices=GroupStatus.choices)

    class Meta:
        model = StudyGroup
        fields = ["course_id", "status"]

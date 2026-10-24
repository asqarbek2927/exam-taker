import django_filters

from apps.academics.models import GroupStudent

from .choices import AttemptStatus
from .models import ExamAttempt


class AttemptFilter(django_filters.FilterSet):
    assignment_id = django_filters.UUIDFilter(field_name="assignment_id")
    exam_id = django_filters.UUIDFilter(field_name="assignment__exam_id")
    course_id = django_filters.UUIDFilter(field_name="assignment__exam__course_id")
    student_id = django_filters.UUIDFilter(field_name="student_id")
    status = django_filters.ChoiceFilter(choices=AttemptStatus.choices)

    class Meta:
        model = ExamAttempt
        fields = ["assignment_id", "exam_id", "course_id", "student_id", "status"]


class PendingGradingFilter(django_filters.FilterSet):
    course_id = django_filters.UUIDFilter(field_name="assignment__exam__course_id")
    exam_id = django_filters.UUIDFilter(field_name="assignment__exam_id")
    assignment_id = django_filters.UUIDFilter(field_name="assignment_id")
    student_id = django_filters.UUIDFilter(field_name="student_id")
    group_id = django_filters.UUIDFilter(method="filter_group")

    class Meta:
        model = ExamAttempt
        fields = ["course_id", "exam_id", "assignment_id", "student_id", "group_id"]

    def filter_group(self, queryset, name, value):
        members = GroupStudent.objects.filter(group_id=value).values("student_id")
        return queryset.filter(student_id__in=members)

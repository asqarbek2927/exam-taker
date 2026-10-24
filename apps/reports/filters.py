import django_filters

from apps.academics.models import GroupStudent
from apps.attempts.models import ExamAttempt

from .selectors import RESULT_STATUSES, only_latest

RESULT_STATUS_CHOICES = [(status, status) for status in RESULT_STATUSES]


class ResultFilter(django_filters.FilterSet):
    course_id = django_filters.UUIDFilter(field_name="assignment__exam__course_id")
    exam_id = django_filters.UUIDFilter(field_name="assignment__exam_id")
    assignment_id = django_filters.UUIDFilter(field_name="assignment_id")
    student_id = django_filters.UUIDFilter(field_name="student_id")
    # E’lonni chiqargan teacher
    teacher_id = django_filters.UUIDFilter(field_name="assignment__published_by_id")
    group_id = django_filters.UUIDFilter(method="filter_group")
    status = django_filters.ChoiceFilter(choices=RESULT_STATUS_CHOICES)
    passed = django_filters.BooleanFilter(field_name="passed")
    date_from = django_filters.DateFilter(field_name="submitted_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="submitted_at", lookup_expr="date__lte")
    latest_only = django_filters.BooleanFilter(method="filter_latest_only")

    class Meta:
        model = ExamAttempt
        fields = [
            "course_id",
            "exam_id",
            "assignment_id",
            "student_id",
            "teacher_id",
            "group_id",
            "status",
            "passed",
            "date_from",
            "date_to",
            "latest_only",
        ]

    def filter_group(self, queryset, name, value):
        members = GroupStudent.objects.filter(group_id=value).values("student_id")
        return queryset.filter(student_id__in=members)

    def filter_latest_only(self, queryset, name, value):
        return only_latest(queryset) if value else queryset

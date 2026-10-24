import django_filters

from .choices import AudienceType, EffectiveStatus
from .models import ExamAssignment


class AssignmentFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=EffectiveStatus.choices, method="filter_status")
    course_id = django_filters.UUIDFilter(field_name="exam__course_id")
    exam_id = django_filters.UUIDFilter(field_name="exam_id")
    audience_type = django_filters.ChoiceFilter(choices=AudienceType.choices)

    class Meta:
        model = ExamAssignment
        fields = ["status", "course_id", "exam_id", "audience_type"]

    def filter_status(self, queryset, name, value):
        # `effective_status` — selectors da annotatsiya qilingan (SCHEDULED/ACTIVE hisoblanadi).
        return queryset.filter(effective_status=value)

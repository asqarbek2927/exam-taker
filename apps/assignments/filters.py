import django_filters

from .choices import AudienceType, EffectiveStatus
from .models import ExamAssignment


class AssignmentFilter(django_filters.FilterSet):
    scope = django_filters.ChoiceFilter(
        choices=(("current", "Current"), ("archived", "Archived"), ("all", "All")),
        method="filter_scope",
    )
    status = django_filters.ChoiceFilter(choices=EffectiveStatus.choices, method="filter_status")
    course_id = django_filters.UUIDFilter(field_name="exam__course_id")
    exam_id = django_filters.UUIDFilter(field_name="exam_id")
    audience_type = django_filters.ChoiceFilter(choices=AudienceType.choices)

    class Meta:
        model = ExamAssignment
        fields = ["status", "course_id", "exam_id", "audience_type", "scope"]

    def filter_status(self, queryset, name, value):
        # `effective_status` — selectors da annotatsiya qilingan (SCHEDULED/ACTIVE hisoblanadi).
        return queryset.filter(effective_status=value)

    def filter_scope(self, queryset, name, value):
        if value == "current":
            return queryset.filter(is_archived=False)
        if value == "archived":
            return queryset.filter(is_archived=True)
        return queryset

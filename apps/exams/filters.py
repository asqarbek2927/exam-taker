import django_filters

from common.filters import parse_uuid_list

from .choices import ExamStatus
from .models import Exam


class ExamFilter(django_filters.FilterSet):
    course_id = django_filters.UUIDFilter(field_name="course_id")
    status = django_filters.ChoiceFilter(choices=ExamStatus.choices)
    # `?creator_ids=a&creator_ids=b` yoki `?creator_ids=a,b`
    creator_ids = django_filters.CharFilter(method="filter_creator_ids")

    class Meta:
        model = Exam
        fields = ["course_id", "status", "creator_ids"]

    def filter_creator_ids(self, queryset, name, value):
        ids = parse_uuid_list(self.data, "creator_ids")
        return queryset.filter(created_by_id__in=ids) if ids else queryset

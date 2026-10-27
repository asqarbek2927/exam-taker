import django_filters

from .models import Notification


class NotificationFilter(django_filters.FilterSet):
    unread_only = django_filters.BooleanFilter(method="filter_unread_only")

    class Meta:
        model = Notification
        fields = ["type", "unread_only"]

    def filter_unread_only(self, queryset, name, value):
        return queryset.filter(read_at__isnull=True) if value else queryset

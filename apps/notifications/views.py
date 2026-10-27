from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.constants import UUID_REGEX

from . import selectors, services
from .filters import NotificationFilter
from .models import Notification
from .serializers import (
    MarkAllReadResponseSerializer,
    NotificationSerializer,
    NotificationSummarySerializer,
)


@extend_schema_view(
    list=extend_schema(tags=["notifications"]),
    retrieve=extend_schema(tags=["notifications"]),
)
class NotificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = NotificationFilter
    ordering_fields = ["created_at", "read_at"]
    ordering = ["-created_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return selectors.notifications_for(self.request.user)

    @extend_schema(tags=["notifications"], responses={200: NotificationSummarySerializer})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        data = selectors.notification_summary(request.user)
        return Response(NotificationSummarySerializer(data).data)

    @extend_schema(tags=["notifications"], request=None, responses={200: NotificationSerializer})
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = services.mark_read(self.get_object())
        return Response(NotificationSerializer(notification).data)

    @extend_schema(
        tags=["notifications"], request=None, responses={200: MarkAllReadResponseSerializer}
    )
    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        return Response({"updated": services.mark_all_read(request.user)})

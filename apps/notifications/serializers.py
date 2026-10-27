from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "type", "title", "message", "data", "is_read", "read_at", "created_at"]
        read_only_fields = fields

    def get_is_read(self, obj: Notification) -> bool:
        return obj.read_at is not None


class NotificationSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    unread = serializers.IntegerField()


class MarkAllReadResponseSerializer(serializers.Serializer):
    updated = serializers.IntegerField()

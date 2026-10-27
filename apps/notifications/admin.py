from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "type", "title", "read_at", "created_at")
    list_filter = ("type", "read_at")
    search_fields = ("recipient__email", "title", "message")
    raw_id_fields = ("recipient",)

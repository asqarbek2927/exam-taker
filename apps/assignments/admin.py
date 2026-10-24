from django.contrib import admin

from .models import ExamAssignment, ExamAssignmentGroup, ExamAssignmentStudent


class GroupInline(admin.TabularInline):
    model = ExamAssignmentGroup
    extra = 0
    raw_id_fields = ("group",)


class StudentInline(admin.TabularInline):
    model = ExamAssignmentStudent
    extra = 0
    raw_id_fields = ("student",)


@admin.register(ExamAssignment)
class ExamAssignmentAdmin(admin.ModelAdmin):
    list_display = ("exam", "audience_type", "status", "start_at", "end_at", "max_attempts")
    list_filter = ("status", "audience_type")
    raw_id_fields = ("exam", "published_by")
    inlines = [GroupInline, StudentInline]

from django.contrib import admin

from .models import Exam, ExamModule, ExamQuestion


class ExamModuleInline(admin.TabularInline):
    model = ExamModule
    extra = 0
    raw_id_fields = ("module",)


class ExamQuestionInline(admin.TabularInline):
    model = ExamQuestion
    extra = 0
    raw_id_fields = ("question",)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "status", "passing_score_percent", "created_by")
    list_filter = ("status", "course")
    search_fields = ("title",)
    raw_id_fields = ("created_by", "course")
    inlines = [ExamModuleInline, ExamQuestionInline]

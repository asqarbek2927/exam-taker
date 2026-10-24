from django.contrib import admin

from .models import ExamAttempt, StudentAnswer


class StudentAnswerInline(admin.TabularInline):
    model = StudentAnswer
    extra = 0
    can_delete = False
    raw_id_fields = ("exam_question", "graded_by")
    readonly_fields = ("text_answer", "is_correct", "points_awarded")


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "assignment", "attempt_number", "status", "score", "passed")
    list_filter = ("status", "passed")
    raw_id_fields = ("assignment", "student")
    inlines = [StudentAnswerInline]

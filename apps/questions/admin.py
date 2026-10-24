from django.contrib import admin

from .models import Question, QuestionOption


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("short_text", "type", "course", "module", "status", "created_by")
    list_filter = ("type", "status", "course")
    search_fields = ("text",)
    raw_id_fields = ("created_by", "module", "course")
    inlines = [QuestionOptionInline]

    @admin.display(description="Savol")
    def short_text(self, obj: Question) -> str:
        return obj.text[:60]

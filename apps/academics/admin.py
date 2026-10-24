from django.contrib import admin

from .models import Course, CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup


class CourseTeacherInline(admin.TabularInline):
    model = CourseTeacher
    extra = 0
    autocomplete_fields = ["teacher"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name",)
    inlines = [CourseTeacherInline]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("course", "student", "status", "enrolled_at")
    list_filter = ("status", "course")
    search_fields = ("student__email", "student__full_name")
    autocomplete_fields = ["student"]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "position", "status")
    list_filter = ("status", "course")
    search_fields = ("title",)


class GroupStudentInline(admin.TabularInline):
    model = GroupStudent
    extra = 0
    autocomplete_fields = ["student"]


@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "created_at")
    list_filter = ("course",)
    search_fields = ("name",)
    inlines = [GroupStudentInline]

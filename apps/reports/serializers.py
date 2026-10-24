from rest_framework import serializers

from apps.attempts.models import ExamAttempt
from apps.exams.serializers import CourseBriefSerializer
from apps.users.serializers import UserBriefSerializer


class ResultSerializer(serializers.ModelSerializer):
    """Yakunlangan attempt natijasi. `PENDING_GRADING` da `score/percentage/passed` — `null`
    (student UI: "Checking in progress")."""

    assignment_id = serializers.UUIDField(read_only=True)
    exam_id = serializers.UUIDField(source="assignment.exam_id", read_only=True)
    exam_title = serializers.CharField(source="assignment.exam.title", read_only=True)
    course = CourseBriefSerializer(source="assignment.exam.course", read_only=True)
    student = UserBriefSerializer(read_only=True)
    is_latest = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "assignment_id",
            "exam_id",
            "exam_title",
            "course",
            "student",
            "attempt_number",
            "status",
            "started_at",
            "submitted_at",
            "score",
            "percentage",
            "passed",
            "is_latest",
        ]
        read_only_fields = fields


# --------------------------------------------------------------------------
# Dashboard (faqat OpenAPI sxemasi va javob shakli uchun)
# --------------------------------------------------------------------------
class AdminDashboardSerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    total_teachers = serializers.IntegerField()
    total_courses = serializers.IntegerField()
    total_modules = serializers.IntegerField()
    total_questions = serializers.IntegerField()
    total_exams = serializers.IntegerField()
    active_assignments = serializers.IntegerField()
    completed_assignments = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
    pass_rate = serializers.FloatField(allow_null=True)


class TeacherDashboardSerializer(serializers.Serializer):
    my_courses = serializers.IntegerField()
    my_groups = serializers.IntegerField()
    my_students = serializers.IntegerField()
    my_questions = serializers.IntegerField()
    my_exams = serializers.IntegerField()
    active_assignments = serializers.IntegerField()
    pending_grading = serializers.IntegerField()
    average_student_score = serializers.FloatField(allow_null=True)


class StudentDashboardSerializer(serializers.Serializer):
    my_courses = serializers.IntegerField()
    available_exams = serializers.IntegerField()
    completed_exams = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
    passed_exams = serializers.IntegerField()

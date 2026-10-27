from rest_framework import serializers

from apps.assignments.models import ExamAssignmentGroup
from apps.attempts.models import ExamAttempt
from apps.exams.serializers import CourseBriefSerializer
from apps.users.serializers import UserBriefSerializer


class ResultGroupSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="group_id", read_only=True)
    name = serializers.CharField(source="group.name", read_only=True)

    class Meta:
        model = ExamAssignmentGroup
        fields = ["id", "name"]
        read_only_fields = fields


class ResultSerializer(serializers.ModelSerializer):
    """Yakunlangan attempt natijasi. `PENDING_GRADING` da `score/percentage/passed` — `null`
    (student UI: "Checking in progress")."""

    assignment_id = serializers.UUIDField(read_only=True)
    exam_id = serializers.UUIDField(source="assignment.exam_id", read_only=True)
    exam_title = serializers.CharField(source="assignment.exam.title", read_only=True)
    course = CourseBriefSerializer(source="assignment.exam.course", read_only=True)
    student = UserBriefSerializer(read_only=True)
    student_avatar_url = serializers.URLField(source="student.avatar_url", read_only=True)
    audience_type = serializers.CharField(source="assignment.audience_type", read_only=True)
    groups = ResultGroupSerializer(source="assignment.assignment_groups", many=True, read_only=True)
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
            "student_avatar_url",
            "audience_type",
            "groups",
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


class ResultSummarySerializer(serializers.Serializer):
    submissions = serializers.IntegerField()
    awaiting_review = serializers.IntegerField()
    graded = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
    grading_progress_percentage = serializers.IntegerField()


# --------------------------------------------------------------------------
# Dashboard (faqat OpenAPI sxemasi va javob shakli uchun)
# --------------------------------------------------------------------------
class QuestionTypeStatisticsSerializer(serializers.Serializer):
    type = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class QuestionStatisticsSerializer(serializers.Serializer):
    total_questions = serializers.IntegerField()
    used_in_exams = serializers.IntegerField()
    used_in_exams_percentage = serializers.FloatField()
    types = QuestionTypeStatisticsSerializer(many=True)


class CourseOverviewSerializer(serializers.Serializer):
    course_id = serializers.UUIDField()
    course_name = serializers.CharField()
    students_count = serializers.IntegerField()
    exams_count = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)


class GrowthSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    added_this_month = serializers.IntegerField()


class CoursesSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    active = serializers.IntegerField()


class QuestionsSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    added_this_month = serializers.IntegerField()


class ExamsSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    active_assignments = serializers.IntegerField()


class UpcomingAssignmentsSummarySerializer(serializers.Serializer):
    next_7_days = serializers.IntegerField()


class DashboardSummarySerializer(serializers.Serializer):
    students = GrowthSummarySerializer()
    teachers = GrowthSummarySerializer()
    courses = CoursesSummarySerializer()
    questions = QuestionsSummarySerializer()
    exams = ExamsSummarySerializer()
    upcoming_assignments = UpcomingAssignmentsSummarySerializer()


class RecentExamSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    course_id = serializers.UUIDField()
    course_name = serializers.CharField()
    created_by_id = serializers.UUIDField()
    created_by_name = serializers.CharField()
    created_at = serializers.DateTimeField()
    status = serializers.CharField()


class RecentResultSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    student_id = serializers.UUIDField()
    student_name = serializers.CharField()
    student_avatar_url = serializers.URLField(allow_blank=True)
    exam_title = serializers.CharField()
    course_name = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    percentage = serializers.FloatField()
    passed = serializers.BooleanField()


class ExamActivityItemSerializer(serializers.Serializer):
    date = serializers.DateField()
    completed_attempts = serializers.IntegerField()


class ExamActivitySerializer(serializers.Serializer):
    period_days = serializers.IntegerField()
    items = ExamActivityItemSerializer(many=True)
    current_total = serializers.IntegerField()
    previous_total = serializers.IntegerField()
    change_percentage = serializers.FloatField(allow_null=True)


class ExamStatisticsSerializer(serializers.Serializer):
    completed_attempts = serializers.IntegerField()
    graded_attempts = serializers.IntegerField()
    passed_attempts = serializers.IntegerField()
    pass_rate = serializers.FloatField(allow_null=True)
    average_score = serializers.FloatField(allow_null=True)
    assigned_recipients = serializers.IntegerField()
    completed_recipients = serializers.IntegerField()
    completion_rate = serializers.FloatField(allow_null=True)
    tracked_submissions = serializers.IntegerField()
    on_time_submissions = serializers.IntegerField()
    on_time_submission_rate = serializers.FloatField(allow_null=True)


class PlatformActivitySerializer(serializers.Serializer):
    type = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    occurred_at = serializers.DateTimeField()


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
    question_statistics = QuestionStatisticsSerializer()
    course_overview = CourseOverviewSerializer(many=True)
    summary = DashboardSummarySerializer()
    recent_exams = RecentExamSerializer(many=True)
    recent_results = RecentResultSerializer(many=True)
    exam_activity = ExamActivitySerializer()
    exam_statistics = ExamStatisticsSerializer()
    platform_activity = PlatformActivitySerializer(many=True)


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

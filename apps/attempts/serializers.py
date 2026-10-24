from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.exams.models import ExamQuestion
from apps.exams.serializers import CourseBriefSerializer
from apps.questions.models import QuestionOption
from apps.questions.serializers import QuestionDetailSerializer
from apps.users.serializers import UserBriefSerializer

from .models import ExamAttempt, StudentAnswer


# --------------------------------------------------------------------------
# Student DTO — `is_correct` HECH QACHON chiqmaydi (TZ 13.1)
# --------------------------------------------------------------------------
class StudentOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ["id", "text"]
        read_only_fields = fields


class StudentSavedAnswerSerializer(serializers.Serializer):
    option_ids = serializers.ListField(child=serializers.UUIDField())
    text_answer = serializers.CharField(allow_blank=True)


class StudentExamQuestionSerializer(serializers.ModelSerializer):
    """`id` — ExamQuestion ID si (javob saqlash shu ID bilan)."""

    question_id = serializers.UUIDField(read_only=True)
    text = serializers.CharField(source="question.text", read_only=True)
    type = serializers.CharField(source="question.type", read_only=True)
    options = StudentOptionSerializer(source="question.options", many=True, read_only=True)
    answer = serializers.SerializerMethodField()

    class Meta:
        model = ExamQuestion
        fields = ["id", "question_id", "text", "type", "points", "position", "options", "answer"]
        read_only_fields = fields

    @extend_schema_field(StudentSavedAnswerSerializer(allow_null=True))
    def get_answer(self, obj: ExamQuestion):
        answer: StudentAnswer | None = self.context.get("answers", {}).get(obj.id)
        if answer is None:
            return None
        return {
            "option_ids": [so.option_id for so in answer.selected_options.all()],
            "text_answer": answer.text_answer,
        }


class _AttemptBaseSerializer(serializers.ModelSerializer):
    assignment_id = serializers.UUIDField(read_only=True)
    exam_id = serializers.UUIDField(source="assignment.exam_id", read_only=True)
    exam_title = serializers.CharField(source="assignment.exam.title", read_only=True)


class StudentAttemptSerializer(_AttemptBaseSerializer):
    """Faol (IN_PROGRESS) attempt: savollar + saqlangan javoblar + taymer."""

    duration_minutes = serializers.IntegerField(
        source="assignment.duration_minutes", read_only=True
    )
    server_now = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "assignment_id",
            "exam_id",
            "exam_title",
            "attempt_number",
            "status",
            "started_at",
            "deadline_at",
            "duration_minutes",
            "server_now",
            "questions",
        ]
        read_only_fields = fields

    def get_server_now(self, obj) -> str:
        return timezone.now().isoformat()

    @extend_schema_field(StudentExamQuestionSerializer(many=True))
    def get_questions(self, obj: ExamAttempt):
        exam_questions = (
            ExamQuestion.objects.filter(exam_id=obj.assignment.exam_id)
            .select_related("question")
            .prefetch_related("question__options")
            .order_by("position")
        )
        answers = {
            answer.exam_question_id: answer
            for answer in obj.answers.prefetch_related("selected_options")
        }
        return StudentExamQuestionSerializer(
            exam_questions, many=True, context={"answers": answers}
        ).data


class AttemptResultSerializer(_AttemptBaseSerializer):
    """Student uchun yakunlangan attempt: faqat natija (to‘g‘ri javoblarsiz)."""

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "assignment_id",
            "exam_id",
            "exam_title",
            "attempt_number",
            "status",
            "started_at",
            "submitted_at",
            "score",
            "percentage",
            "passed",
        ]
        read_only_fields = fields


# --------------------------------------------------------------------------
# Ro‘yxat / Staff detail
# --------------------------------------------------------------------------
class AttemptListSerializer(_AttemptBaseSerializer):
    course = CourseBriefSerializer(source="assignment.exam.course", read_only=True)
    student = UserBriefSerializer(read_only=True)

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
            "deadline_at",
            "submitted_at",
            "score",
            "percentage",
            "passed",
        ]
        read_only_fields = fields


class StaffAnswerSerializer(serializers.ModelSerializer):
    exam_question_id = serializers.UUIDField(read_only=True)
    position = serializers.IntegerField(source="exam_question.position", read_only=True)
    max_points = serializers.DecimalField(
        source="exam_question.points", max_digits=6, decimal_places=2, read_only=True
    )
    question = QuestionDetailSerializer(source="exam_question.question", read_only=True)
    selected_option_ids = serializers.SerializerMethodField()
    graded_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = StudentAnswer
        fields = [
            "id",
            "exam_question_id",
            "position",
            "max_points",
            "question",
            "selected_option_ids",
            "text_answer",
            "is_correct",
            "points_awarded",
            "teacher_feedback",
            "graded_by",
            "graded_at",
        ]
        read_only_fields = fields

    def get_selected_option_ids(self, obj: StudentAnswer) -> list:
        return [so.option_id for so in obj.selected_options.all()]


class AttemptStaffDetailSerializer(AttemptListSerializer):
    answers = StaffAnswerSerializer(many=True, read_only=True)

    class Meta(AttemptListSerializer.Meta):
        fields = [*AttemptListSerializer.Meta.fields, "answers"]
        read_only_fields = fields


# --------------------------------------------------------------------------
# Autosave
# --------------------------------------------------------------------------
class AnswerInputSerializer(serializers.Serializer):
    """Tanlovli savol: `option_ids` (bo‘sh ro‘yxat — tozalash). OPEN_ENDED: `text_answer`."""

    option_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, max_length=50
    )
    text_answer = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False, max_length=20000
    )


class AnswerSerializer(serializers.ModelSerializer):
    exam_question_id = serializers.UUIDField(read_only=True)
    option_ids = serializers.SerializerMethodField()

    class Meta:
        model = StudentAnswer
        fields = ["exam_question_id", "option_ids", "text_answer", "updated_at"]
        read_only_fields = fields

    def get_option_ids(self, obj: StudentAnswer) -> list:
        return [so.option_id for so in obj.selected_options.all()]


# --------------------------------------------------------------------------
# Manual grading
# --------------------------------------------------------------------------
class PendingAttemptSerializer(AttemptListSerializer):
    pending_answers_count = serializers.IntegerField(read_only=True)

    class Meta(AttemptListSerializer.Meta):
        fields = [*AttemptListSerializer.Meta.fields, "pending_answers_count"]
        read_only_fields = fields


class GradeInputSerializer(serializers.Serializer):
    points_awarded = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    teacher_feedback = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class AttemptSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamAttempt
        fields = ["id", "status", "score", "percentage", "passed"]
        read_only_fields = fields


class GradeResponseSerializer(serializers.Serializer):
    answer = StaffAnswerSerializer()
    attempt = AttemptSummarySerializer()

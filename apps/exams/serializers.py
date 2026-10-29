from decimal import Decimal

from rest_framework import serializers

from apps.academics.models import Course, Module
from apps.questions.models import Question
from apps.questions.serializers import POINTS_FIELD, QuestionDetailSerializer
from apps.users.serializers import UserBriefSerializer
from common.fields import UUIDRelatedField

from .choices import ExamStatus, ExamWritableStatus
from .models import Exam, ExamModule, ExamQuestion
from .selectors import exam_is_locked

PERCENT_FIELD = {
    "max_digits": 5,
    "decimal_places": 2,
    "min_value": Decimal("0"),
    "max_value": Decimal("100"),
}


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
class CourseBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["id", "name", "status"]
        read_only_fields = fields


class ExamModuleSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="module_id", read_only=True)
    title = serializers.CharField(source="module.title", read_only=True)
    position = serializers.IntegerField(source="module.position", read_only=True)
    status = serializers.CharField(source="module.status", read_only=True)

    class Meta:
        model = ExamModule
        fields = ["id", "title", "position", "status"]
        read_only_fields = fields


class ExamQuestionSerializer(serializers.ModelSerializer):
    """`id` — ExamQuestion ID si (attempt javoblari shunga bog‘lanadi)."""

    question = QuestionDetailSerializer(read_only=True)

    class Meta:
        model = ExamQuestion
        fields = ["id", "position", "points", "question"]
        read_only_fields = fields


class ExamListSerializer(serializers.ModelSerializer):
    course = CourseBriefSerializer(read_only=True)
    created_by = UserBriefSerializer(read_only=True)
    questions_count = serializers.IntegerField(read_only=True)
    modules_count = serializers.IntegerField(read_only=True)
    uses_count = serializers.IntegerField(read_only=True)
    total_points = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id",
            "course",
            "created_by",
            "title",
            "description",
            "passing_score_percent",
            "status",
            "questions_count",
            "modules_count",
            "total_points",
            "uses_count",
            "created_at",
            "updated_at",
            "version",
        ]
        read_only_fields = fields


class ExamLibrarySummarySerializer(serializers.Serializer):
    total_exams = serializers.IntegerField()
    draft_exams = serializers.IntegerField()
    ready_exams = serializers.IntegerField()
    archived_exams = serializers.IntegerField()


class ExamDetailSerializer(ExamListSerializer):
    modules = ExamModuleSerializer(source="exam_modules", many=True, read_only=True)
    questions = ExamQuestionSerializer(source="exam_questions", many=True, read_only=True)
    is_locked = serializers.SerializerMethodField()

    class Meta(ExamListSerializer.Meta):
        fields = [*ExamListSerializer.Meta.fields, "modules", "questions", "is_locked"]
        read_only_fields = fields

    def get_is_locked(self, obj: Exam) -> bool:
        return exam_is_locked(obj)


class ExamDuplicateResponseSerializer(ExamDetailSerializer):
    skipped_question_ids = serializers.ListField(child=serializers.UUIDField(), read_only=True)

    class Meta(ExamDetailSerializer.Meta):
        fields = [*ExamDetailSerializer.Meta.fields, "skipped_question_ids"]
        read_only_fields = fields


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------
class ExamQuestionInputSerializer(serializers.Serializer):
    question_id = UUIDRelatedField(queryset=Question.objects.all(), source="question")
    points = serializers.DecimalField(required=False, **POINTS_FIELD)
    position = serializers.IntegerField(min_value=1, required=False)


class ExamCreateSerializer(serializers.Serializer):
    course_id = UUIDRelatedField(queryset=Course.objects.all(), source="course")
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    passing_score_percent = serializers.DecimalField(**PERCENT_FIELD)
    status = serializers.ChoiceField(choices=ExamWritableStatus.choices, default=ExamStatus.DRAFT)
    module_ids = UUIDRelatedField(
        queryset=Module.objects.all(), many=True, source="modules", required=False
    )
    questions = ExamQuestionInputSerializer(many=True, required=False)

    def validate(self, attrs):
        attrs.setdefault("modules", [])
        attrs.setdefault("questions", [])
        return attrs


class ExamUpdateSerializer(serializers.Serializer):
    """PATCH. `module_ids` / `questions` yuborilsa — to‘plam to‘liq almashtiriladi."""

    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    passing_score_percent = serializers.DecimalField(required=False, **PERCENT_FIELD)
    status = serializers.ChoiceField(choices=ExamWritableStatus.choices, required=False)
    module_ids = UUIDRelatedField(
        queryset=Module.objects.all(), many=True, source="modules", required=False
    )
    questions = ExamQuestionInputSerializer(many=True, required=False)

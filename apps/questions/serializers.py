from decimal import Decimal

from rest_framework import serializers

from apps.academics.models import Course, Module
from apps.users.serializers import UserBriefSerializer
from common.fields import UUIDRelatedField

from .choices import QuestionType
from .models import Question, QuestionOption
from .validators import validate_options

POINTS_FIELD = {"max_digits": 6, "decimal_places": 2, "min_value": Decimal("0.01")}


# --------------------------------------------------------------------------
# Read (Teacher / Super Admin ko‘radi — `is_correct` bilan)
# --------------------------------------------------------------------------
class QuestionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ["id", "text", "is_correct", "position"]
        read_only_fields = fields


class QuestionCourseBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ["id", "name", "status"]
        read_only_fields = fields


class QuestionModuleBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["id", "title", "position", "status"]
        read_only_fields = fields


class QuestionListSerializer(serializers.ModelSerializer):
    course_id = serializers.UUIDField(read_only=True)
    module_id = serializers.UUIDField(read_only=True)
    course = QuestionCourseBriefSerializer(read_only=True)
    module = QuestionModuleBriefSerializer(read_only=True)
    created_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = Question
        fields = [
            "id",
            "course_id",
            "module_id",
            "course",
            "module",
            "type",
            "text",
            "default_points",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class QuestionBankSummarySerializer(serializers.Serializer):
    active_questions = serializers.IntegerField()
    choice_questions = serializers.IntegerField()
    open_ended = serializers.IntegerField()
    archived = serializers.IntegerField()


class QuestionDetailSerializer(QuestionListSerializer):
    options = QuestionOptionSerializer(many=True, read_only=True)

    class Meta(QuestionListSerializer.Meta):
        fields = [*QuestionListSerializer.Meta.fields, "options"]
        read_only_fields = fields


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------
class QuestionOptionInputSerializer(serializers.Serializer):
    text = serializers.CharField()
    is_correct = serializers.BooleanField(default=False)


class QuestionCreateSerializer(serializers.Serializer):
    course_id = UUIDRelatedField(queryset=Course.objects.all(), source="course")
    module_id = UUIDRelatedField(queryset=Module.objects.all(), source="module")
    type = serializers.ChoiceField(choices=QuestionType.choices)
    text = serializers.CharField()
    default_points = serializers.DecimalField(required=False, **POINTS_FIELD)
    options = QuestionOptionInputSerializer(many=True, required=False)

    def validate(self, attrs):
        attrs.setdefault("options", [])
        errors = validate_options(attrs["type"], attrs["options"])
        if errors:
            raise serializers.ValidationError({"options": errors})
        return attrs


class QuestionUpdateSerializer(serializers.Serializer):
    """PATCH. `options` yuborilsa — to‘liq almashtiriladi. `type` o‘zgarsa `options` majburiy."""

    module_id = UUIDRelatedField(queryset=Module.objects.all(), source="module", required=False)
    type = serializers.ChoiceField(choices=QuestionType.choices, required=False)
    text = serializers.CharField(required=False)
    default_points = serializers.DecimalField(required=False, **POINTS_FIELD)
    options = QuestionOptionInputSerializer(many=True, required=False)

    def validate(self, attrs):
        question: Question = self.instance
        new_type = attrs.get("type", question.type)
        if "options" in attrs:
            errors = validate_options(new_type, attrs["options"])
            if errors:
                raise serializers.ValidationError({"options": errors})
        elif new_type != question.type:
            raise serializers.ValidationError(
                {"options": ["Savol turi o‘zgarsa, options ham yuborilishi shart."]}
            )
        return attrs

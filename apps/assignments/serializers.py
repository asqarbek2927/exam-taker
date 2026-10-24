from rest_framework import serializers

from apps.academics.models import StudyGroup
from apps.exams.models import Exam
from apps.exams.serializers import CourseBriefSerializer
from apps.users.choices import UserRole
from apps.users.models import User
from apps.users.serializers import UserBriefSerializer
from common.fields import UUIDRelatedField

from .choices import AssignmentStatus, AudienceType, EffectiveStatus
from .models import ExamAssignment, ExamAssignmentGroup, ExamAssignmentStudent
from .selectors import eligible_students


# --------------------------------------------------------------------------
# Read (Super Admin / Teacher)
# --------------------------------------------------------------------------
class ExamBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = ["id", "title", "status"]
        read_only_fields = fields


class AssignmentGroupSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="group_id", read_only=True)
    name = serializers.CharField(source="group.name", read_only=True)

    class Meta:
        model = ExamAssignmentGroup
        fields = ["id", "name"]
        read_only_fields = fields


class AssignmentStudentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="student_id", read_only=True)
    full_name = serializers.CharField(source="student.full_name", read_only=True)
    email = serializers.EmailField(source="student.email", read_only=True)

    class Meta:
        model = ExamAssignmentStudent
        fields = ["id", "full_name", "email"]
        read_only_fields = fields


class AssignmentSerializer(serializers.ModelSerializer):
    exam = ExamBriefSerializer(read_only=True)
    course = CourseBriefSerializer(source="exam.course", read_only=True)
    published_by = UserBriefSerializer(read_only=True)
    status = serializers.ChoiceField(
        choices=EffectiveStatus.choices, source="effective_status", read_only=True
    )
    stored_status = serializers.ChoiceField(
        choices=AssignmentStatus.choices, source="status", read_only=True
    )
    attempts_count = serializers.IntegerField(read_only=True)
    groups = AssignmentGroupSerializer(source="assignment_groups", many=True, read_only=True)
    students = AssignmentStudentSerializer(source="assignment_students", many=True, read_only=True)

    class Meta:
        model = ExamAssignment
        fields = [
            "id",
            "exam",
            "course",
            "published_by",
            "audience_type",
            "groups",
            "students",
            "start_at",
            "end_at",
            "duration_minutes",
            "max_attempts",
            "status",
            "stored_status",
            "attempts_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AssignmentDetailSerializer(AssignmentSerializer):
    eligible_students_count = serializers.SerializerMethodField()

    class Meta(AssignmentSerializer.Meta):
        fields = [*AssignmentSerializer.Meta.fields, "eligible_students_count"]
        read_only_fields = fields

    def get_eligible_students_count(self, obj: ExamAssignment) -> int:
        return eligible_students(obj).count()


# --------------------------------------------------------------------------
# Read (Student)
# --------------------------------------------------------------------------
class StudentAssignmentSerializer(serializers.ModelSerializer):
    exam_id = serializers.UUIDField(read_only=True)
    exam_title = serializers.CharField(source="exam.title", read_only=True)
    course = CourseBriefSerializer(source="exam.course", read_only=True)
    status = serializers.ChoiceField(
        choices=EffectiveStatus.choices, source="effective_status", read_only=True
    )
    questions_count = serializers.IntegerField(read_only=True)
    total_points = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    attempts_used = serializers.IntegerField(read_only=True)
    attempts_remaining = serializers.SerializerMethodField()
    active_attempt_id = serializers.UUIDField(read_only=True, allow_null=True)
    can_start = serializers.SerializerMethodField()

    class Meta:
        model = ExamAssignment
        fields = [
            "id",
            "exam_id",
            "exam_title",
            "course",
            "start_at",
            "end_at",
            "duration_minutes",
            "max_attempts",
            "status",
            "questions_count",
            "total_points",
            "attempts_used",
            "attempts_remaining",
            "active_attempt_id",
            "can_start",
        ]
        read_only_fields = fields

    def get_attempts_remaining(self, obj) -> int | None:
        if obj.max_attempts is None:
            return None
        return max(obj.max_attempts - obj.attempts_used, 0)

    def get_can_start(self, obj) -> bool:
        remaining = self.get_attempts_remaining(obj)
        return (
            obj.effective_status == EffectiveStatus.ACTIVE
            and obj.active_attempt_id is None
            and (remaining is None or remaining > 0)
        )


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------
class _AudienceMixin:
    """`audience_type` bilan `group_ids` / `student_ids` mosligi (shakl darajasida, 422)."""

    def _check_audience_shape(self, audience_type, groups, students) -> None:
        errors: dict[str, list[str]] = {}
        if audience_type == AudienceType.ALL_COURSE_STUDENTS:
            if groups:
                errors["group_ids"] = ["ALL_COURSE_STUDENTS uchun berilmaydi."]
            if students:
                errors["student_ids"] = ["ALL_COURSE_STUDENTS uchun berilmaydi."]
        elif audience_type == AudienceType.GROUPS:
            if not groups:
                errors["group_ids"] = ["GROUPS uchun kamida 1 ta guruh kerak."]
            if students:
                errors["student_ids"] = ["GROUPS uchun berilmaydi."]
        elif audience_type == AudienceType.SPECIFIC_STUDENTS:
            if not students:
                errors["student_ids"] = ["SPECIFIC_STUDENTS uchun kamida 1 ta student kerak."]
            if groups:
                errors["group_ids"] = ["SPECIFIC_STUDENTS uchun berilmaydi."]
        if errors:
            raise serializers.ValidationError(errors)


class AssignmentCreateSerializer(_AudienceMixin, serializers.Serializer):
    exam_id = UUIDRelatedField(queryset=Exam.objects.all(), source="exam")
    audience_type = serializers.ChoiceField(choices=AudienceType.choices)
    group_ids = UUIDRelatedField(
        queryset=StudyGroup.objects.all(), many=True, source="groups", required=False
    )
    student_ids = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.STUDENT),
        many=True,
        source="students",
        required=False,
    )
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField(allow_null=True)  # null = deadline yo‘q
    duration_minutes = serializers.IntegerField(min_value=1, max_value=1440)
    max_attempts = serializers.IntegerField(min_value=1, allow_null=True)  # null = cheksiz
    is_draft = serializers.BooleanField(default=False)

    def validate(self, attrs):
        attrs.setdefault("groups", [])
        attrs.setdefault("students", [])
        if attrs["end_at"] is not None and attrs["end_at"] <= attrs["start_at"]:
            raise serializers.ValidationError(
                {"end_at": ["`end_at` `start_at` dan keyin bo‘lishi kerak."]}
            )
        self._check_audience_shape(attrs["audience_type"], attrs["groups"], attrs["students"])
        return attrs


class AssignmentUpdateSerializer(_AudienceMixin, serializers.Serializer):
    """PATCH. Audience o‘zgarsa `group_ids`/`student_ids` to‘liq almashtiriladi."""

    audience_type = serializers.ChoiceField(choices=AudienceType.choices, required=False)
    group_ids = UUIDRelatedField(
        queryset=StudyGroup.objects.all(), many=True, source="groups", required=False
    )
    student_ids = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.STUDENT),
        many=True,
        source="students",
        required=False,
    )
    start_at = serializers.DateTimeField(required=False)
    end_at = serializers.DateTimeField(required=False, allow_null=True)
    duration_minutes = serializers.IntegerField(min_value=1, max_value=1440, required=False)
    max_attempts = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate(self, attrs):
        # To‘liq (audience_type + ro‘yxat) berilgan holatdagina shakl tekshiriladi;
        # qolgan holatlarni service joriy holatga qarab tekshiradi.
        if "audience_type" in attrs and ("groups" in attrs or "students" in attrs):
            self._check_audience_shape(
                attrs["audience_type"], attrs.get("groups", []), attrs.get("students", [])
            )
        return attrs

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.users.choices import UserRole
from apps.users.models import User
from apps.users.serializers import UserBriefSerializer
from common.fields import UUIDRelatedField

from .choices import CourseTeacherType, EnrollmentStatus
from .models import Course, CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
class CourseWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)


class CourseListSerializer(serializers.ModelSerializer):
    teachers_count = serializers.IntegerField(read_only=True)
    students_count = serializers.IntegerField(read_only=True)
    groups_count = serializers.IntegerField(read_only=True)
    modules_count = serializers.IntegerField(read_only=True)
    questions_count = serializers.IntegerField(read_only=True)
    exams_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Course
        fields = [
            "id",
            "name",
            "description",
            "status",
            "teachers_count",
            "students_count",
            "groups_count",
            "modules_count",
            "questions_count",
            "exams_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CourseDetailSerializer(CourseListSerializer):
    main_teacher = serializers.SerializerMethodField()
    support_teachers = serializers.SerializerMethodField()

    class Meta(CourseListSerializer.Meta):
        fields = [*CourseListSerializer.Meta.fields, "main_teacher", "support_teachers"]
        read_only_fields = fields

    @extend_schema_field(UserBriefSerializer(allow_null=True))
    def get_main_teacher(self, obj: Course):
        # `course_teachers` selectors.with_course_stats() da prefetch qilingan.
        for ct in obj.course_teachers.all():
            if ct.type == CourseTeacherType.MAIN:
                return UserBriefSerializer(ct.teacher).data
        return None

    @extend_schema_field(UserBriefSerializer(many=True))
    def get_support_teachers(self, obj: Course):
        return [
            UserBriefSerializer(ct.teacher).data
            for ct in obj.course_teachers.all()
            if ct.type == CourseTeacherType.SUPPORT
        ]


# --------------------------------------------------------------------------
# CourseTeacher
# --------------------------------------------------------------------------
class CourseTeacherSerializer(serializers.ModelSerializer):
    teacher = UserBriefSerializer(read_only=True)

    class Meta:
        model = CourseTeacher
        fields = ["id", "teacher", "type", "assigned_at"]
        read_only_fields = fields


class CourseTeacherCreateSerializer(serializers.Serializer):
    teacher_id = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.TEACHER), source="teacher"
    )
    type = serializers.ChoiceField(choices=CourseTeacherType.choices)


class CourseTeacherUpdateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=CourseTeacherType.choices)


# --------------------------------------------------------------------------
# Enrollment
# --------------------------------------------------------------------------
class EnrollmentSerializer(serializers.ModelSerializer):
    student = UserBriefSerializer(read_only=True)

    class Meta:
        model = Enrollment
        fields = ["id", "student", "status", "enrolled_at"]
        read_only_fields = fields


class EnrollmentCreateSerializer(serializers.Serializer):
    student_id = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.STUDENT), source="student"
    )


class EnrollmentUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=EnrollmentStatus.choices)


# --------------------------------------------------------------------------
# Module
# --------------------------------------------------------------------------
class ModuleWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    position = serializers.IntegerField(min_value=1, required=False)


class QuestionPreviewSerializer(serializers.Serializer):
    """Modul ro‘yxatida ko‘rsatiladigan savol preview (`?with_questions=true`)."""

    id = serializers.UUIDField(read_only=True)
    type = serializers.CharField(read_only=True)
    text = serializers.CharField(read_only=True)
    default_points = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)


class ModuleSerializer(serializers.ModelSerializer):
    question_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Module
        fields = [
            "id",
            "title",
            "description",
            "position",
            "status",
            "question_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ModuleWithQuestionsSerializer(ModuleSerializer):
    questions = QuestionPreviewSerializer(source="preview_questions", many=True, read_only=True)

    class Meta(ModuleSerializer.Meta):
        fields = [*ModuleSerializer.Meta.fields, "questions"]
        read_only_fields = fields


# --------------------------------------------------------------------------
# StudyGroup
# --------------------------------------------------------------------------
class GroupWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)


class GroupSerializer(serializers.ModelSerializer):
    students_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = StudyGroup
        fields = ["id", "name", "students_count", "created_at", "updated_at"]
        read_only_fields = fields


class GroupStudentSerializer(serializers.ModelSerializer):
    student = UserBriefSerializer(read_only=True)

    class Meta:
        model = GroupStudent
        fields = ["id", "student", "added_at"]
        read_only_fields = fields


class GroupStudentCreateSerializer(serializers.Serializer):
    student_id = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.STUDENT), source="student"
    )

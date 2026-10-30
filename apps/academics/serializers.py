from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.users.choices import EDUCATOR_ROLES, UserRole
from apps.users.models import User
from apps.users.serializers import UserBriefSerializer
from common.fields import UUIDRelatedField

from .choices import CourseStatus, CourseTeacherType, EnrollmentStatus, GroupStatus, ModuleStatus
from .models import Course, CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
class CourseWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=[CourseStatus.DRAFT, CourseStatus.ACTIVE], required=False
    )


class CourseMutationSerializer(serializers.Serializer):
    """TZ course payload; camelCase va eski snake_case nomlarini qabul qiladi."""

    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=[CourseStatus.DRAFT, CourseStatus.ACTIVE], required=False
    )
    main_teacher_id = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.TEACHER),
        source="main_teacher",
        required=False,
        allow_null=True,
    )
    teacher_ids = UUIDRelatedField(
        queryset=User.objects.filter(role__in=EDUCATOR_ROLES),
        source="teachers",
        many=True,
        required=False,
    )
    version = serializers.IntegerField(min_value=1, required=False)

    def to_internal_value(self, data):
        data = data.copy()
        aliases = {"mainTeacherId": "main_teacher_id", "teacherIds": "teacher_ids"}
        for source, target in aliases.items():
            if source in data and target not in data:
                data[target] = data[source]
        return super().to_internal_value(data)

    def validate(self, attrs):
        main = attrs.get("main_teacher", serializers.empty)
        teachers = attrs.get("teachers")
        if main is not serializers.empty and main is not None and teachers is not None:
            teacher_ids = {teacher.pk for teacher in teachers}
            teacher_ids.add(main.pk)
            attrs["teachers"] = list(
                User.objects.filter(pk__in=teacher_ids).order_by("full_name", "pk")
            )
        return attrs


class CourseStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=CourseStatus.choices)
    version = serializers.IntegerField(min_value=1, required=False)


class CourseListSerializer(serializers.ModelSerializer):
    teachers = serializers.SerializerMethodField()
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
            "version",
            "teachers",
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

    @extend_schema_field(UserBriefSerializer(many=True))
    def get_teachers(self, obj: Course):
        # `course_teachers` selectors.with_course_stats() da prefetch qilingan.
        return [UserBriefSerializer(item.teacher).data for item in obj.course_teachers.all()]


class CourseDetailSerializer(CourseListSerializer):
    main_teacher = serializers.SerializerMethodField()
    support_teachers = serializers.SerializerMethodField()
    modules = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(CourseListSerializer.Meta):
        fields = [
            *CourseListSerializer.Meta.fields,
            "main_teacher",
            "support_teachers",
            "modules",
            "actions",
        ]
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

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_modules(self, obj: Course):
        from .selectors import course_modules

        queryset = course_modules(obj).exclude(status=ModuleStatus.ARCHIVED)
        return ModuleSerializer(queryset, many=True).data

    @extend_schema_field(serializers.DictField(child=serializers.BooleanField()))
    def get_actions(self, obj: Course):
        request = self.context.get("request")
        role = getattr(getattr(request, "user", None), "role", None)
        is_admin = role == UserRole.SUPER_ADMIN
        is_educator = role in EDUCATOR_ROLES
        editable = obj.status != CourseStatus.ARCHIVED
        return {
            "can_edit": is_admin and editable,
            "can_change_status": is_admin,
            "can_manage_enrollments": is_admin and obj.status == CourseStatus.ACTIVE,
            "can_manage_modules": (is_admin or is_educator) and editable,
        }


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
        queryset=User.objects.filter(role__in=EDUCATOR_ROLES), source="teacher"
    )
    type = serializers.ChoiceField(choices=CourseTeacherType.choices)

    def validate(self, attrs):
        if (
            attrs["teacher"].role == UserRole.SUPPORT_TEACHER
            and attrs["type"] == CourseTeacherType.MAIN
        ):
            raise serializers.ValidationError(
                {"type": ["SUPPORT_TEACHER faqat SUPPORT sifatida biriktiriladi."]}
            )
        return attrs


class CourseTeacherUpdateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=CourseTeacherType.choices)


# --------------------------------------------------------------------------
# Enrollment
# --------------------------------------------------------------------------
class EnrollmentGroupSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class EnrollmentResultSummarySerializer(serializers.Serializer):
    attempts_count = serializers.IntegerField()
    graded_count = serializers.IntegerField()
    passed_count = serializers.IntegerField()
    average_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)


class EnrollmentSerializer(serializers.ModelSerializer):
    student = UserBriefSerializer(read_only=True)
    group = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    result_summary = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "student",
            "status",
            "enrolled_at",
            "group",
            "progress",
            "result_summary",
        ]
        read_only_fields = fields

    @extend_schema_field(EnrollmentGroupSerializer(allow_null=True))
    def get_group(self, obj: Enrollment):
        membership = (
            GroupStudent.objects.filter(group__course=obj.course, student=obj.student)
            .select_related("group")
            .first()
        )
        if membership is None:
            return None
        return {"id": str(membership.group_id), "name": membership.group.name}

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_progress(self, _obj: Enrollment):
        # TZ progress formulasi bermagan; taxminiy foiz chiqarilmaydi.
        return None

    @extend_schema_field(EnrollmentResultSummarySerializer)
    def get_result_summary(self, obj: Enrollment):
        from django.db.models import Avg, Count, Q

        from apps.attempts.choices import AttemptStatus
        from apps.attempts.models import ExamAttempt

        return ExamAttempt.objects.filter(
            student=obj.student, assignment__exam__course=obj.course
        ).aggregate(
            attempts_count=Count("pk"),
            graded_count=Count("pk", filter=Q(status=AttemptStatus.GRADED)),
            passed_count=Count("pk", filter=Q(passed=True)),
            average_percentage=Avg("percentage"),
        )


class EnrollmentCreateSerializer(serializers.Serializer):
    student_id = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.STUDENT), source="student"
    )

    def to_internal_value(self, data):
        data = data.copy()
        if "studentId" in data and "student_id" not in data:
            data["student_id"] = data["studentId"]
        return super().to_internal_value(data)


class EnrollmentUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=EnrollmentStatus.choices)


# --------------------------------------------------------------------------
# Module
# --------------------------------------------------------------------------
class ModuleWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    position = serializers.IntegerField(min_value=1, required=False)

    def to_internal_value(self, data):
        data = data.copy()
        if "order" in data and "position" not in data:
            data["position"] = data["order"]
        return super().to_internal_value(data)


class ModuleStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ModuleStatus.choices)


class ModuleOrderSerializer(serializers.Serializer):
    module_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)

    def to_internal_value(self, data):
        data = data.copy()
        if "moduleIds" in data and "module_ids" not in data:
            data["module_ids"] = data["moduleIds"]
        return super().to_internal_value(data)


class AcademicStudentCourseCardSerializer(serializers.Serializer):
    course_id = serializers.UUIDField(source="id", read_only=True)
    title = serializers.CharField(source="name", read_only=True)
    description = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    teacher_names = serializers.SerializerMethodField()
    module_count = serializers.IntegerField(source="modules_count", read_only=True)
    progress = serializers.SerializerMethodField()
    next_step = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_teacher_names(self, obj: Course):
        return [item.teacher.full_name for item in obj.course_teachers.all()]

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_progress(self, _obj: Course):
        return None

    @extend_schema_field(serializers.CharField())
    def get_next_step(self, _obj: Course):
        return "VIEW_AVAILABLE_EXAMS"


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
    main_teacher_id = UUIDRelatedField(
        queryset=User.objects.filter(role=UserRole.TEACHER),
        source="main_teacher",
        required=False,
        allow_null=True,
    )
    support_teacher_id = UUIDRelatedField(
        queryset=User.objects.filter(role__in=EDUCATOR_ROLES),
        source="support_teacher",
        required=False,
        allow_null=True,
    )

    def to_internal_value(self, data):
        data = data.copy()
        aliases = {
            "mainTeacherId": "main_teacher_id",
            "supportTeacherId": "support_teacher_id",
        }
        for source, target in aliases.items():
            if source in data and target not in data:
                data[target] = data[source]
        return super().to_internal_value(data)


class GroupUpdateSerializer(GroupWriteSerializer):
    version = serializers.IntegerField(min_value=1, required=False)


class GroupDirectoryWriteSerializer(GroupWriteSerializer):
    course_id = UUIDRelatedField(queryset=Course.objects.all(), source="course")
    status = serializers.ChoiceField(choices=GroupStatus.choices, required=False)

    def to_internal_value(self, data):
        data = data.copy()
        if "courseId" in data and "course_id" not in data:
            data["course_id"] = data["courseId"]
        return super().to_internal_value(data)


class GroupStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=GroupStatus.choices)
    version = serializers.IntegerField(min_value=1, required=False)


class GroupCourseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class GroupSerializer(serializers.ModelSerializer):
    students_count = serializers.IntegerField(read_only=True)
    course = GroupCourseSerializer(read_only=True)
    main_teacher = UserBriefSerializer(read_only=True)
    support_teacher = UserBriefSerializer(read_only=True)
    students_preview = serializers.SerializerMethodField()

    class Meta:
        model = StudyGroup
        fields = [
            "id",
            "name",
            "status",
            "version",
            "course",
            "main_teacher",
            "support_teacher",
            "students_count",
            "students_preview",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(UserBriefSerializer(many=True))
    def get_students_preview(self, obj: StudyGroup):
        memberships = getattr(obj, "student_memberships", [])
        request = self.context.get("request")
        if getattr(getattr(request, "user", None), "role", None) == UserRole.STUDENT:
            memberships = [item for item in memberships if item.student_id == request.user.id]
        memberships = memberships[:3]
        return [UserBriefSerializer(item.student).data for item in memberships]


class GroupDetailSerializer(GroupSerializer):
    students = serializers.SerializerMethodField()

    class Meta(GroupSerializer.Meta):
        fields = [*GroupSerializer.Meta.fields, "students"]
        read_only_fields = fields

    @extend_schema_field(UserBriefSerializer(many=True))
    def get_students(self, obj: StudyGroup):
        request = self.context.get("request")
        if getattr(getattr(request, "user", None), "role", None) == UserRole.STUDENT:
            return []
        memberships = getattr(obj, "student_memberships", [])
        return [UserBriefSerializer(item.student).data for item in memberships]


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

    def to_internal_value(self, data):
        data = data.copy()
        if "studentId" in data and "student_id" not in data:
            data["student_id"] = data["studentId"]
        return super().to_internal_value(data)


class CourseCatalogSummarySerializer(serializers.Serializer):
    total_courses = serializers.IntegerField()
    active_courses = serializers.IntegerField()
    draft_courses = serializers.IntegerField()
    archived_courses = serializers.IntegerField()
    learning_modules = serializers.IntegerField()
    course_enrollments = serializers.IntegerField()


class GroupDirectorySummarySerializer(serializers.Serializer):
    active_groups = serializers.IntegerField()
    grouped_students = serializers.IntegerField()
    teaching_pairs = serializers.IntegerField()
    archived_groups = serializers.IntegerField()

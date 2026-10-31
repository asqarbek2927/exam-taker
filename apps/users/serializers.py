import re

from django.contrib.auth import password_validation
from django.contrib.auth.models import update_last_login
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .choices import (
    EDUCATOR_ROLES,
    CreatableUserRole,
    UserRole,
    UserStatus,
)
from .models import User


def validate_password_strength(value: str, user: User | None = None) -> str:
    errors = []
    if not re.search(r"[A-Z]", value):
        errors.append("Passwordda kamida bitta katta harf bo‘lishi kerak.")
    if not re.search(r"[a-z]", value):
        errors.append("Passwordda kamida bitta kichik harf bo‘lishi kerak.")
    if not re.search(r"[0-9]", value):
        errors.append("Passwordda kamida bitta raqam bo‘lishi kerak.")
    if errors:
        raise serializers.ValidationError(errors)
    try:
        password_validation.validate_password(value, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc
    return value


# --------------------------------------------------------------------------
# User
# --------------------------------------------------------------------------
class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "email", "role"]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "username",
            "role",
            "avatar_url",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: User) -> str:
        if not obj.avatar:
            return obj.avatar_url
        request = self.context.get("request")
        return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url


class CurrentUserSerializer(UserSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "phone_number",
            "must_change_password",
            "permissions",
        ]
        read_only_fields = fields

    def get_permissions(self, obj: User) -> dict[str, bool]:
        is_admin = obj.role == UserRole.SUPER_ADMIN
        has_course = False
        is_support_teacher = False
        if obj.role in EDUCATOR_ROLES:
            from apps.academics.choices import CourseStatus, CourseTeacherType

            assignments = obj.course_assignments.filter(course__status=CourseStatus.ACTIVE)
            has_course = assignments.exists()
            is_support_teacher = assignments.filter(type=CourseTeacherType.SUPPORT).exists()
        return {
            "can_create_question": is_admin or has_course,
            "can_create_exam": is_admin or has_course,
            "can_assign_exam": is_admin or has_course,
            "can_grade": is_admin or has_course,
            "is_support_teacher": is_support_teacher,
        }


class TeacherCourseSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="course_id", read_only=True)
    name = serializers.CharField(source="course.name", read_only=True)
    teacher_type = serializers.CharField(source="type", read_only=True)


class TeacherDirectorySerializer(UserSerializer):
    assigned_courses = TeacherCourseSerializer(
        source="active_course_assignments", many=True, read_only=True
    )
    courses_count = serializers.IntegerField(read_only=True)
    students_count = serializers.IntegerField(read_only=True)
    exams_count = serializers.IntegerField(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "assigned_courses",
            "courses_count",
            "students_count",
            "exams_count",
        ]
        read_only_fields = fields


class TeacherDirectorySummarySerializer(serializers.Serializer):
    active_teachers = serializers.IntegerField()
    inactive_teachers = serializers.IntegerField()
    total_teachers = serializers.IntegerField()
    students_taught = serializers.IntegerField()
    course_assignments = serializers.IntegerField()


class StudentCourseSerializer(serializers.Serializer):
    enrollment_id = serializers.UUIDField(source="id", read_only=True)
    course_id = serializers.UUIDField(read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    status = serializers.CharField(read_only=True)


class StudentDirectorySerializer(UserSerializer):
    enrolled_courses = StudentCourseSerializer(
        source="active_enrollments", many=True, read_only=True
    )
    courses_count = serializers.IntegerField(read_only=True)
    exams_taken = serializers.IntegerField(read_only=True)
    average_score = serializers.FloatField(read_only=True, allow_null=True)
    passed_exams = serializers.IntegerField(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "enrolled_courses",
            "courses_count",
            "exams_taken",
            "average_score",
            "passed_exams",
        ]
        read_only_fields = fields


class StudentDirectorySummarySerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    active_students = serializers.IntegerField()
    inactive_students = serializers.IntegerField()
    course_enrollments = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
    passed_exams = serializers.IntegerField()


# --------------------------------------------------------------------------
# Admin accounts (TZ #10-19)
# --------------------------------------------------------------------------
class AdminAssignedCourseSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="course_id", read_only=True)
    name = serializers.CharField(source="course.name", read_only=True)


class AdminAccountSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()
    assigned_courses = serializers.SerializerMethodField()
    courses_count = serializers.SerializerMethodField()
    students_count = serializers.SerializerMethodField()
    exams_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "username",
            "email",
            "role",
            "status",
            "phone_number",
            "location",
            "avatar_url",
            "must_change_password",
            "created_at",
            "updated_at",
            "version",
            "assigned_courses",
            "courses_count",
            "students_count",
            "exams_count",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: User) -> str:
        return UserSerializer(obj, context=self.context).data["avatar_url"]

    @extend_schema_field(AdminAssignedCourseSerializer(many=True))
    def get_assigned_courses(self, obj: User) -> list[dict]:
        from apps.academics.choices import CourseStatus

        assignments = getattr(obj, "active_course_assignments", None)
        if assignments is None:
            assignments = obj.course_assignments.filter(
                course__status=CourseStatus.ACTIVE
            ).select_related("course")
        return AdminAssignedCourseSerializer(assignments, many=True).data

    def get_courses_count(self, obj: User) -> int:
        return getattr(obj, "courses_count", len(self.get_assigned_courses(obj)))

    def get_students_count(self, obj: User) -> int:
        if hasattr(obj, "students_count"):
            return obj.students_count
        from apps.academics.choices import CourseStatus, EnrollmentStatus
        from apps.academics.models import Enrollment

        return (
            Enrollment.objects.filter(
                course__course_teachers__teacher=obj,
                course__status=CourseStatus.ACTIVE,
                status=EnrollmentStatus.ACTIVE,
                student__status=UserStatus.ACTIVE,
            )
            .values("student_id")
            .distinct()
            .count()
        )

    def get_exams_count(self, obj: User) -> int:
        if hasattr(obj, "exams_count"):
            return obj.exams_count
        from apps.academics.choices import CourseStatus
        from apps.exams.choices import ExamStatus
        from apps.exams.models import Exam

        return Exam.objects.filter(
            course__course_teachers__teacher=obj,
            course__status=CourseStatus.ACTIVE,
            status__in=[ExamStatus.DRAFT, ExamStatus.READY],
        ).count()


class AdminAccountSummaryQuerySerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[UserRole.TEACHER, UserRole.SUPPORT_TEACHER])


class AdminAccountRoleSummarySerializer(serializers.Serializer):
    total_accounts = serializers.IntegerField()
    active_accounts = serializers.IntegerField()
    inactive_accounts = serializers.IntegerField()
    students_taught = serializers.IntegerField()
    course_assignments = serializers.IntegerField()


class AdminAccountDetailSerializer(AdminAccountSerializer):
    courses = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()
    exam_stats = serializers.SerializerMethodField()
    last_active = serializers.DateTimeField(source="last_login", read_only=True, allow_null=True)

    class Meta(AdminAccountSerializer.Meta):
        fields = [
            *AdminAccountSerializer.Meta.fields,
            "courses",
            "groups",
            "exam_stats",
            "last_active",
        ]
        read_only_fields = fields

    def get_courses(self, obj: User) -> list[dict]:
        from apps.academics.models import CourseTeacher, Enrollment

        if obj.role in EDUCATOR_ROLES:
            return [
                {
                    "id": item.course_id,
                    "name": item.course.name,
                    "status": item.course.status,
                    "teacher_type": item.type,
                    "groups_count": item.course.groups.count(),
                    "students_count": item.course.enrollments.filter(status="ACTIVE").count(),
                }
                for item in CourseTeacher.objects.filter(teacher=obj)
                .select_related("course")
                .order_by("course__name")
            ]
        if obj.role == UserRole.STUDENT:
            from django.db.models import OuterRef, Subquery

            course_teacher_name = (
                CourseTeacher.objects.filter(
                    course_id=OuterRef("course_id"),
                )
                .order_by("type", "assigned_at")
                .values("teacher__full_name")[:1]
            )
            return [
                {
                    "id": item.course_id,
                    "name": item.course.name,
                    "status": item.status,
                    "enrolled_at": item.enrolled_at,
                    "teacher_name": item.teacher_name,
                    # Kurs progressi uchun tasdiqlangan formula/model hali mavjud emas.
                    "progress": None,
                    "groups_count": item.course.groups.count(),
                    "students_count": item.course.enrollments.filter(status="ACTIVE").count(),
                }
                for item in Enrollment.objects.filter(student=obj)
                .annotate(teacher_name=Subquery(course_teacher_name))
                .select_related("course")
                .order_by("course__name")
            ]
        return []

    def get_groups(self, obj: User) -> list[dict]:
        from django.db.models import Q

        from apps.academics.models import GroupStudent, StudyGroup

        if obj.role in EDUCATOR_ROLES:
            groups = StudyGroup.objects.filter(
                Q(main_teacher=obj) | Q(support_teacher=obj)
            ).select_related("course")
            return [
                {
                    "id": group.pk,
                    "name": group.name,
                    "course_id": group.course_id,
                    "course_name": group.course.name,
                    "status": group.status,
                }
                for group in groups.order_by("course__name", "name")
            ]
        if obj.role == UserRole.STUDENT:
            return [
                {
                    "id": item.group_id,
                    "name": item.group.name,
                    "course_id": item.group.course_id,
                    "course_name": item.group.course.name,
                    "status": item.group.status,
                }
                for item in GroupStudent.objects.filter(student=obj)
                .select_related("group__course")
                .order_by("group__course__name", "group__name")
            ]
        return []

    def get_exam_stats(self, obj: User) -> dict[str, int]:
        from apps.assignments.models import ExamAssignment
        from apps.attempts.choices import AttemptStatus
        from apps.attempts.models import ExamAttempt
        from apps.exams.models import Exam

        if obj.role in EDUCATOR_ROLES:
            return {
                "created_exams": Exam.objects.filter(created_by=obj).count(),
                "published_assignments": ExamAssignment.objects.filter(published_by=obj).count(),
                "graded_attempts": ExamAttempt.objects.filter(
                    answers__graded_by=obj, status=AttemptStatus.GRADED
                )
                .distinct()
                .count(),
            }
        if obj.role == UserRole.STUDENT:
            attempts = ExamAttempt.objects.filter(student=obj)
            return {
                "attempts": attempts.count(),
                "graded_attempts": attempts.filter(status=AttemptStatus.GRADED).count(),
                "passed_attempts": attempts.filter(
                    status=AttemptStatus.GRADED, passed=True
                ).count(),
            }
        return {"created_exams": 0, "published_assignments": 0, "graded_attempts": 0}


class AdminAccountCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=CreatableUserRole.choices)
    phone_number = serializers.RegexField(
        regex=r"^\+998\d{9}$", required=False, allow_blank=True, default=""
    )
    location = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Bu email allaqachon ro‘yxatdan o‘tgan.")
        return value

    def validate(self, attrs):
        forbidden = {
            "password",
            "generate_random_password",
            "course_ids",
            "group_ids",
        }.intersection(self.initial_data)
        if forbidden:
            raise serializers.ValidationError(
                {name: ["Bu maydon account yaratishda qabul qilinmaydi."] for name in forbidden}
            )
        return attrs


class AdminAccountCreateResponseSerializer(serializers.Serializer):
    account = AdminAccountDetailSerializer()
    temporary_password = serializers.CharField()
    temporary_password_expires_at = serializers.DateTimeField()


class AdminAccountUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(max_length=254, required=False)
    avatar = serializers.ImageField(required=False, write_only=True)
    phone_number = serializers.RegexField(regex=r"^\+998\d{9}$", required=False, allow_blank=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    version = serializers.IntegerField(min_value=1)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        queryset = User.objects.filter(email__iexact=value)
        user = self.context.get("user")
        if user is not None:
            queryset = queryset.exclude(pk=user.pk)
        if queryset.exists():
            raise serializers.ValidationError("Bu email allaqachon ro'yxatdan o'tgan.")
        return value

    def validate_avatar(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Rasm hajmi 5 MB dan oshmasligi kerak.")
        if getattr(value, "content_type", "") not in {"image/jpeg", "image/png", "image/webp"}:
            raise serializers.ValidationError("Faqat JPEG, PNG yoki WEBP rasm yuboring.")
        return value

    def validate(self, attrs):
        forbidden = {"role", "status"}.intersection(self.initial_data)
        if forbidden:
            raise serializers.ValidationError(
                {name: ["Bu maydon ushbu endpoint orqali o‘zgartirilmaydi."] for name in forbidden}
            )
        if len(attrs) == 1:
            raise serializers.ValidationError("Versiondan tashqari kamida bitta maydon yuboring.")
        return attrs


class AdminAccountStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[UserStatus.ACTIVE, UserStatus.INACTIVE])
    version = serializers.IntegerField(min_value=1)


class AccountVersionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)


class TeachingCoursesUpdateSerializer(serializers.Serializer):
    course_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
    main_course_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, required=False, default=list
    )
    version = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        if len(set(attrs["course_ids"])) != len(attrs["course_ids"]):
            raise serializers.ValidationError({"course_ids": ["Takroriy ID yuborilmang."]})
        if len(set(attrs["main_course_ids"])) != len(attrs["main_course_ids"]):
            raise serializers.ValidationError({"main_course_ids": ["Takroriy ID yuborilmang."]})
        return attrs


class AccountActivitySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    actor_id = serializers.UUIDField(allow_null=True)
    action = serializers.CharField()
    metadata = serializers.JSONField()
    created_at = serializers.DateTimeField()


class AccountCourseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    teacher_type = serializers.CharField(required=False)
    enrolled_at = serializers.DateTimeField(required=False)
    teacher_name = serializers.CharField(required=False, allow_null=True)
    progress = serializers.FloatField(required=False, allow_null=True, min_value=0, max_value=100)
    groups_count = serializers.IntegerField()
    students_count = serializers.IntegerField()


class ProfileUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    phone_number = serializers.RegexField(
        regex=r"^\+?[0-9][0-9\s().-]{6,31}$", required=False, allow_blank=True
    )

    def validate(self, attrs):
        forbidden = {"email", "role", "status"}.intersection(self.initial_data)
        if forbidden:
            raise serializers.ValidationError(
                {name: ["Bu maydon profil orqali o‘zgartirilmaydi."] for name in forbidden}
            )
        user: User = self.context["user"]
        if user.role != UserRole.SUPER_ADMIN and "full_name" in self.initial_data:
            raise serializers.ValidationError(
                {"full_name": ["Bu maydonni faqat Super Admin o‘zgartira oladi."]}
            )
        if not attrs:
            raise serializers.ValidationError("Kamida bitta maydon yuboring.")
        if "phone_number" in attrs:
            attrs["phone_number"] = attrs["phone_number"].strip()
        return attrs


# Eski importlar uchun alias; /auth/me ham shu xavfsiz qoidalardan foydalanadi.
CurrentUserUpdateSerializer = ProfileUpdateSerializer


class AvatarUploadSerializer(serializers.Serializer):
    image = serializers.ImageField(
        write_only=True,
        help_text="Multipart rasm fayli. Eski klientlar uchun `avatar` kaliti ham qabul qilinadi.",
    )

    def to_internal_value(self, data):
        """Model nomidagi `avatar` kalitini schema'ni ko'paytirmasdan qabul qiladi."""
        if data.get("image"):
            return super().to_internal_value(data)
        if data.get("avatar"):
            # QueryDict.copy() TemporaryUploadedFile'ni deepcopy qiladi va katta faylda 500 beradi.
            return super().to_internal_value({"image": data.get("avatar")})
        return super().to_internal_value(data)

    def validate_image(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Rasm hajmi 5 MB dan oshmasligi kerak.")
        if getattr(value, "content_type", "") not in {"image/jpeg", "image/png", "image/webp"}:
            raise serializers.ValidationError("Faqat JPEG, PNG yoki WEBP rasm yuboring.")
        return value


class AvatarResponseSerializer(serializers.Serializer):
    avatar_url = serializers.URLField(allow_blank=True)
    updated_at = serializers.DateTimeField()


class ChangeOwnPasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    confirm_new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128, required=False
    )

    def validate(self, attrs):
        user: User = self.context["user"]
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": ["Joriy password noto‘g‘ri."]})
        if (
            "confirm_new_password" in attrs
            and attrs["new_password"] != attrs["confirm_new_password"]
        ):
            raise serializers.ValidationError(
                {"confirm_new_password": ["Yangi passwordlar mos kelmadi."]}
            )
        if attrs["new_password"] == attrs["current_password"]:
            raise serializers.ValidationError(
                {"new_password": ["Yangi password joriy passworddan farq qilishi kerak."]}
            )
        validate_password_strength(attrs["new_password"], user=user)
        return attrs


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginSerializer(serializers.Serializer):
    emailOrUsername = serializers.CharField(
        trim_whitespace=True,
        write_only=True,
        help_text=(
            "Email yoki username. `email` va `email_or_username` legacy aliaslari ham "
            "qabul qilinadi."
        ),
    )
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    default_error_messages = {
        "no_active_account": "Email yoki parol noto‘g‘ri, yoki akkaunt faol emas.",
    }

    def to_internal_value(self, data):
        """Legacy login kalitlarini OpenAPI'da ko'rsatmasdan canonical nomga o'tkazadi."""
        normalized = data.copy()
        legacy_identifier = data.get("email_or_username") or data.get("email")
        if not normalized.get("emailOrUsername") and legacy_identifier:
            normalized["emailOrUsername"] = legacy_identifier
        return super().to_internal_value(normalized)

    def validate(self, attrs):
        identifier = (attrs.get("emailOrUsername") or "").strip()
        errors = {}
        if not identifier:
            errors["emailOrUsername"] = ["Email yoki username kiriting."]
        if not attrs.get("password"):
            errors["password"] = ["Password kiriting."]
        if errors:
            raise serializers.ValidationError(errors)
        user = User.objects.filter(email__iexact=identifier).first()
        if user is None:
            user = User.objects.filter(username__iexact=identifier).first()
        if user is None or not user.is_active or not user.check_password(attrs["password"]):
            raise AuthenticationFailed(self.error_messages["no_active_account"])
        if (
            user.must_change_password
            and user.temporary_password_expires_at
            and user.temporary_password_expires_at <= timezone.now()
        ):
            raise AuthenticationFailed("Vaqtinchalik parol muddati tugagan.")
        self.user = user
        refresh = RefreshToken.for_user(user)
        update_last_login(None, user)
        return {
            "user": UserBriefSerializer(user).data,
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "must_change_password": user.must_change_password,
        }


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()

    def validate(self, attrs):
        try:
            token = RefreshToken(attrs["refresh_token"])
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc
        user = User.objects.filter(pk=token.payload.get("user_id")).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed("Akkaunt topilmadi yoki faol emas.")
        if (
            user.must_change_password
            and user.temporary_password_expires_at
            and user.temporary_password_expires_at <= timezone.now()
        ):
            raise AuthenticationFailed("Vaqtinchalik parol muddati tugagan.")
        inner = TokenRefreshSerializer(data={"refresh": attrs["refresh_token"]})
        try:
            inner.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc
        except AuthenticationFailed as exc:
            raise AuthenticationFailed("Akkaunt topilmadi yoki faol emas.") from exc
        data = inner.validated_data
        # ROTATE_REFRESH_TOKENS=True bo‘lgani uchun `refresh` har doim qaytadi.
        return {"access_token": data["access"], "refresh_token": data.get("refresh")}


class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(write_only=True)


class LoginResponseSerializer(serializers.Serializer):
    """Faqat OpenAPI sxemasi uchun."""

    user = UserBriefSerializer()
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    must_change_password = serializers.BooleanField()


class RefreshResponseSerializer(serializers.Serializer):
    """Faqat OpenAPI sxemasi uchun."""

    access_token = serializers.CharField()
    refresh_token = serializers.CharField()

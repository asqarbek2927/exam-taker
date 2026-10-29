import re

from django.contrib.auth import password_validation
from django.contrib.auth.models import update_last_login
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .choices import CreatableUserRole, UserLanguage, UserRole, UserTheme
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
    preferences = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "phone_number",
            "must_change_password",
            "permissions",
            "preferences",
        ]
        read_only_fields = fields

    def get_permissions(self, obj: User) -> dict[str, bool]:
        is_admin = obj.role == UserRole.SUPER_ADMIN
        has_course = False
        is_support_teacher = False
        if obj.role == UserRole.TEACHER:
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

    def get_preferences(self, obj: User) -> dict[str, str]:
        return {"language": obj.language, "theme": obj.theme}


class UserCreateResponseSerializer(UserSerializer):
    """`generated_password` faqat create javobida bir marta ko‘rsatiladi."""

    generated_password = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "generated_password"]
        read_only_fields = fields

    def get_generated_password(self, obj: User) -> str | None:
        return self.context.get("generated_password")


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


class UserCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128, required=False
    )
    generate_random_password = serializers.BooleanField(write_only=True, required=False)
    # SUPER_ADMIN API orqali yaratilmaydi (faqat `createsuperuser`).
    role = serializers.ChoiceField(choices=CreatableUserRole.choices)
    avatar_url = serializers.URLField(
        max_length=500,
        required=False,
        default="",
        allow_blank=True,
        allow_null=True,
        help_text="Ixtiyoriy. Yuborilmasa bo‘sh qiymat saqlanadi.",
    )

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Bu email allaqachon ro‘yxatdan o‘tgan.")
        return value

    def validate(self, attrs):
        password_given = "password" in attrs
        generate_given = "generate_random_password" in attrs
        generate_random = attrs.get("generate_random_password", False)
        if generate_random and password_given:
            raise serializers.ValidationError(
                {"password": ["Random parol so‘ralganda `password` yuborilmasligi kerak."]}
            )
        if generate_given and not generate_random and not password_given:
            raise serializers.ValidationError(
                {"password": ["Password kiriting yoki random yaratishni tanlang."]}
            )
        if password_given:
            probe = User(full_name=attrs["full_name"], email=attrs["email"])
            validate_password_strength(attrs["password"], user=probe)
        attrs["avatar_url"] = attrs.get("avatar_url") or ""
        return attrs


class UserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(max_length=254, required=False)
    avatar_url = serializers.URLField(max_length=500, required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Bu email allaqachon ro‘yxatdan o‘tgan.")
        return value


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


class PreferencesUpdateSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=UserLanguage.choices, required=False)
    theme = serializers.ChoiceField(choices=UserTheme.choices, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Kamida bitta preference yuboring.")
        return attrs


class PreferencesSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=UserLanguage.choices)
    theme = serializers.ChoiceField(choices=UserTheme.choices)


class AvatarUploadSerializer(serializers.Serializer):
    image = serializers.ImageField(write_only=True)

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


class SetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_password(self, value: str) -> str:
        return validate_password_strength(value, user=self.context.get("target_user"))


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginSerializer(serializers.Serializer):
    emailOrUsername = serializers.CharField(required=False, trim_whitespace=True, write_only=True)
    email_or_username = serializers.CharField(required=False, trim_whitespace=True)
    email = serializers.EmailField(required=False, write_only=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False, required=False)

    default_error_messages = {
        "no_active_account": "Email yoki parol noto‘g‘ri, yoki akkaunt faol emas.",
    }

    def validate(self, attrs):
        identifier = (
            attrs.get("emailOrUsername")
            or attrs.get("email_or_username")
            or attrs.get("email")
            or ""
        ).strip()
        errors = {}
        if not identifier:
            errors["email_or_username"] = ["Email yoki username kiriting."]
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

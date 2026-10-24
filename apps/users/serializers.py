from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer

from .choices import CreatableUserRole
from .models import User


def validate_password_strength(value: str, user: User | None = None) -> str:
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
    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "role",
            "avatar_url",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class UserCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    # SUPER_ADMIN API orqali yaratilmaydi (faqat `createsuperuser`).
    role = serializers.ChoiceField(choices=CreatableUserRole.choices)
    avatar_url = serializers.URLField(max_length=500, required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Bu email allaqachon ro‘yxatdan o‘tgan.")
        return value

    def validate(self, attrs):
        probe = User(full_name=attrs["full_name"], email=attrs["email"])
        validate_password_strength(attrs["password"], user=probe)
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


class SetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_password(self, value: str) -> str:
        return validate_password_strength(value, user=self.context.get("target_user"))


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        "no_active_account": "Email yoki parol noto‘g‘ri, yoki akkaunt faol emas.",
    }

    def validate(self, attrs):
        data = super().validate(attrs)
        return {
            "user": UserBriefSerializer(self.user).data,
            "access_token": data["access"],
            "refresh_token": data["refresh"],
        }


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()

    def validate(self, attrs):
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


class RefreshResponseSerializer(serializers.Serializer):
    """Faqat OpenAPI sxemasi uchun."""

    access_token = serializers.CharField()
    refresh_token = serializers.CharField()

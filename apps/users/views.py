from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from common.constants import UUID_REGEX
from common.exceptions import BusinessRuleError
from common.permissions import IsSuperAdmin
from common.throttling import LoginIPRateThrottle, LoginRateThrottle

from . import selectors, services
from .choices import UserRole
from .filters import PersonFilter, StudentDirectoryFilter, TeacherDirectoryFilter, UserFilter
from .models import User
from .serializers import (
    AvatarResponseSerializer,
    AvatarUploadSerializer,
    ChangeOwnPasswordSerializer,
    CurrentUserSerializer,
    CurrentUserUpdateSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
    PreferencesSerializer,
    PreferencesUpdateSerializer,
    ProfileUpdateSerializer,
    RefreshResponseSerializer,
    RefreshSerializer,
    SetPasswordSerializer,
    StudentDirectorySerializer,
    StudentDirectorySummarySerializer,
    TeacherDirectorySerializer,
    TeacherDirectorySummarySerializer,
    UserCreateResponseSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class PublicAuthView(APIView):
    """Tokensiz chaqiriladigan auth endpointlar.

    `get_authenticate_header` bo‘lmasa DRF 401 ni 403 ga aylantirib yuboradi.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginIPRateThrottle]

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'


@extend_schema(
    tags=["auth"],
    request=LoginSerializer,
    responses={200: LoginResponseSerializer},
    auth=[],
)
class LoginView(PublicAuthView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["auth"],
    request=RefreshSerializer,
    responses={200: RefreshResponseSerializer},
    auth=[],
)
class RefreshView(PublicAuthView):
    throttle_classes = [LoginIPRateThrottle]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["auth"],
    request=LogoutSerializer,
    responses={204: OpenApiResponse(description="Refresh token bekor qilindi.")},
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh_token"])
        except TokenError as exc:
            raise BusinessRuleError(
                "Refresh token yaroqsiz yoki allaqachon bekor qilingan."
            ) from exc
        if str(token.payload.get("user_id")) != str(request.user.pk):
            raise BusinessRuleError("Bu refresh token sizga tegishli emas.")
        token.blacklist()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"], responses={200: CurrentUserSerializer})
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(CurrentUserSerializer(request.user, context={"request": request}).data)

    @extend_schema(
        tags=["auth"], request=CurrentUserUpdateSerializer, responses={200: CurrentUserSerializer}
    )
    def patch(self, request):
        serializer = CurrentUserUpdateSerializer(
            data=request.data, partial=True, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        user = services.update_current_user(request.user, **serializer.validated_data)
        return Response(CurrentUserSerializer(user, context={"request": request}).data)


@extend_schema(tags=["profile"], responses={200: CurrentUserSerializer})
class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(CurrentUserSerializer(request.user, context={"request": request}).data)

    @extend_schema(
        tags=["profile"], request=ProfileUpdateSerializer, responses={200: CurrentUserSerializer}
    )
    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            data=request.data, partial=True, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        user = services.update_current_user(request.user, **serializer.validated_data)
        return Response(CurrentUserSerializer(user, context={"request": request}).data)


@extend_schema(tags=["profile"])
class ProfilePhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=AvatarUploadSerializer, responses={200: AvatarResponseSerializer})
    def post(self, request):
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.replace_avatar(request.user, serializer.validated_data["image"])
        avatar_url = request.build_absolute_uri(user.avatar.url)
        return Response({"avatar_url": avatar_url, "updated_at": user.updated_at})

    @extend_schema(responses={204: OpenApiResponse(description="Profil rasmi o‘chirildi.")})
    def delete(self, request):
        services.delete_avatar(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["profile"])
class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PreferencesUpdateSerializer, responses={200: PreferencesSerializer})
    def patch(self, request):
        serializer = PreferencesUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = services.update_preferences(request.user, **serializer.validated_data)
        return Response({"language": user.language, "theme": user.theme})


@extend_schema(
    tags=["auth"],
    request=ChangeOwnPasswordSerializer,
    responses={204: OpenApiResponse(description="Password o‘zgartirildi.")},
)
class ChangeOwnPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangeOwnPasswordSerializer(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)
        services.set_user_password(
            user=request.user, password=serializer.validated_data["new_password"]
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Users (Super Admin)
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["users"]),
    retrieve=extend_schema(tags=["users"]),
    create=extend_schema(
        tags=["users"],
        request=UserCreateSerializer,
        responses={201: UserCreateResponseSerializer},
        examples=[
            OpenApiExample(
                "Random password (avatarsiz)",
                value={
                    "full_name": "Ali Valiyev",
                    "email": "ali@example.com",
                    "generate_random_password": True,
                    "role": "STUDENT",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Custom password (avatarsiz)",
                value={
                    "full_name": "Vali Aliyev",
                    "email": "vali@example.com",
                    "password": "Strong-Pass123!",
                    "role": "TEACHER",
                },
                request_only=True,
            ),
        ],
    ),
    partial_update=extend_schema(
        tags=["users"], request=UserUpdateSerializer, responses={200: UserSerializer}
    ),
)
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Foydalanuvchilarni boshqarish. Hard delete yo‘q — `deactivate`."""

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsSuperAdmin]
    filterset_class = UserFilter
    search_fields = ["full_name", "email"]
    ordering_fields = ["full_name", "email", "created_at"]
    ordering = ["full_name", "email"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        fields.pop("generate_random_password", None)
        user, generated_password = services.create_user(**fields)
        data = UserCreateResponseSerializer(
            user, context={"generated_password": generated_password}
        ).data
        return Response(data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = services.update_user(user, **serializer.validated_data)
        return Response(UserSerializer(user).data)

    @extend_schema(tags=["users"], request=None, responses={200: UserSerializer})
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = services.activate_user(user=self.get_object())
        return Response(UserSerializer(user).data)

    @extend_schema(tags=["users"], request=None, responses={200: UserSerializer})
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = services.deactivate_user(user=self.get_object(), acting_user=request.user)
        return Response(UserSerializer(user).data)

    @extend_schema(
        tags=["users"],
        request=SetPasswordSerializer,
        responses={204: OpenApiResponse(description="Parol o‘zgartirildi.")},
    )
    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        user = self.get_object()
        serializer = SetPasswordSerializer(data=request.data, context={"target_user": user})
        serializer.is_valid(raise_exception=True)
        services.set_user_password(user=user, password=serializer.validated_data["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class _RoleScopedReadOnlyViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    role: str
    serializer_class = UserSerializer
    permission_classes = [IsSuperAdmin]
    filterset_class = PersonFilter
    search_fields = ["full_name", "email"]
    ordering_fields = ["full_name", "email", "created_at"]
    ordering = ["full_name", "email"]
    lookup_value_regex = UUID_REGEX

    def get_queryset(self):
        return User.objects.filter(role=self.role)


@extend_schema_view(
    list=extend_schema(tags=["teachers"]), retrieve=extend_schema(tags=["teachers"])
)
class TeacherViewSet(_RoleScopedReadOnlyViewSet):
    role = UserRole.TEACHER
    serializer_class = TeacherDirectorySerializer
    filterset_class = TeacherDirectoryFilter
    ordering_fields = ["full_name", "email", "created_at", "courses_count", "students_count"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return selectors.teacher_directory()

    @extend_schema(
        tags=["teachers"],
        responses={200: TeacherDirectorySummarySerializer},
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(selectors.teacher_directory_summary())


@extend_schema_view(
    list=extend_schema(tags=["students"]), retrieve=extend_schema(tags=["students"])
)
class StudentViewSet(_RoleScopedReadOnlyViewSet):
    role = UserRole.STUDENT
    serializer_class = StudentDirectorySerializer
    filterset_class = StudentDirectoryFilter
    ordering_fields = [
        "full_name",
        "email",
        "created_at",
        "courses_count",
        "exams_taken",
        "average_score",
        "passed_exams",
    ]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return selectors.student_directory()

    @extend_schema(
        tags=["students"],
        responses={200: StudentDirectorySummarySerializer},
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(selectors.student_directory_summary())

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from common.constants import UUID_REGEX
from common.exceptions import BusinessRuleError
from common.permissions import IsSuperAdmin
from common.throttling import LoginIPRateThrottle, LoginRateThrottle

from . import services
from .choices import UserRole
from .filters import PersonFilter, UserFilter
from .models import User
from .serializers import (
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshResponseSerializer,
    RefreshSerializer,
    SetPasswordSerializer,
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


@extend_schema(tags=["auth"], responses={200: UserSerializer})
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# --------------------------------------------------------------------------
# Users (Super Admin)
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["users"]),
    retrieve=extend_schema(tags=["users"]),
    create=extend_schema(
        tags=["users"], request=UserCreateSerializer, responses={201: UserSerializer}
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
        user = services.create_user(**serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

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


@extend_schema_view(
    list=extend_schema(tags=["students"]), retrieve=extend_schema(tags=["students"])
)
class StudentViewSet(_RoleScopedReadOnlyViewSet):
    role = UserRole.STUDENT

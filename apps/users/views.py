from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
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
    AccountActivitySerializer,
    AccountCourseSerializer,
    AccountVersionSerializer,
    AdminAccountCreateResponseSerializer,
    AdminAccountCreateSerializer,
    AdminAccountDetailSerializer,
    AdminAccountRoleSummarySerializer,
    AdminAccountSerializer,
    AdminAccountStatusSerializer,
    AdminAccountSummaryQuerySerializer,
    AdminAccountUpdateSerializer,
    AvatarResponseSerializer,
    AvatarUploadSerializer,
    ChangeOwnPasswordSerializer,
    CurrentUserSerializer,
    CurrentUserUpdateSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
    ProfileUpdateSerializer,
    RefreshResponseSerializer,
    RefreshSerializer,
    StudentDirectorySerializer,
    StudentDirectorySummarySerializer,
    TeacherDirectorySerializer,
    TeacherDirectorySummarySerializer,
    TeachingCoursesUpdateSerializer,
    UserSerializer,
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
        exclude=True,
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
# Admin accounts (TZ #10-19)
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["admin-accounts"]),
    retrieve=extend_schema(tags=["admin-accounts"], responses={200: AdminAccountDetailSerializer}),
    create=extend_schema(
        tags=["admin-accounts"],
        request=AdminAccountCreateSerializer,
        responses={201: AdminAccountCreateResponseSerializer},
    ),
    partial_update=extend_schema(
        tags=["admin-accounts"],
        request=AdminAccountUpdateSerializer,
        responses={200: AdminAccountDetailSerializer},
    ),
    update=extend_schema(
        tags=["admin-accounts"],
        request=AdminAccountUpdateSerializer,
        responses={200: AdminAccountDetailSerializer},
    ),
    destroy=extend_schema(
        tags=["admin-accounts"],
        request=AccountVersionSerializer,
        responses={204: OpenApiResponse(description="Account soft-delete qilindi.")},
    ),
)
class AdminAccountViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsSuperAdmin]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_class = UserFilter
    search_fields = ["full_name", "email", "username", "phone_number", "location"]
    ordering_fields = [
        "full_name",
        "email",
        "role",
        "status",
        "created_at",
        "last_login",
        "courses_count",
        "students_count",
        "exams_count",
    ]
    ordering = ["full_name", "email"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return selectors.admin_accounts()

    def get_serializer_class(self):
        if self.action == "list":
            return AdminAccountSerializer
        return AdminAccountDetailSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["summary"] = selectors.admin_account_summary()
        return response

    @extend_schema(
        tags=["admin-accounts"],
        parameters=[AdminAccountSummaryQuerySerializer],
        responses={200: AdminAccountRoleSummarySerializer},
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        query = AdminAccountSummaryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(selectors.admin_account_role_summary(query.validated_data["role"]))

    def create(self, request, *args, **kwargs):
        serializer = AdminAccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, password, _issued_at, expires_at = services.create_admin_account(
            actor=request.user, **serializer.validated_data
        )
        payload = {
            "account": AdminAccountDetailSerializer(user, context={"request": request}).data,
            "temporary_password": password,
            "temporary_password_expires_at": expires_at,
        }
        return Response(payload, status=status.HTTP_201_CREATED)

    def _update_account(self, request, *, partial: bool):
        account = self.get_object()
        serializer = AdminAccountUpdateSerializer(
            data=request.data,
            partial=partial,
            context={"user": account},
        )
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        expected_version = fields.pop("version")
        user = services.update_admin_account(
            user=account,
            actor=request.user,
            expected_version=expected_version,
            **fields,
        )
        return Response(AdminAccountDetailSerializer(user, context={"request": request}).data)

    def update(self, request, *args, **kwargs):
        return self._update_account(request, partial=False)

    def partial_update(self, request, *args, **kwargs):
        return self._update_account(request, partial=True)

    @extend_schema(
        tags=["admin-accounts"],
        parameters=[
            OpenApiParameter(
                name="version",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Accountning joriy optimistic-lock versiyasi.",
            )
        ],
        request=None,
        responses={200: AdminAccountDetailSerializer},
    )
    @action(detail=True, methods=["delete"], url_path="photo")
    def photo(self, request, pk=None):
        version_data = request.data if request.data.get("version") else request.query_params
        serializer = AccountVersionSerializer(data=version_data)
        serializer.is_valid(raise_exception=True)
        user = services.delete_admin_account_avatar(
            user=self.get_object(),
            actor=request.user,
            expected_version=serializer.validated_data["version"],
        )
        return Response(AdminAccountDetailSerializer(user, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        serializer = AccountVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.soft_delete_account(
            user=self.get_object(),
            actor=request.user,
            expected_version=serializer.validated_data["version"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["admin-accounts"],
        request=AdminAccountStatusSerializer,
        responses={200: AdminAccountDetailSerializer},
    )
    @action(detail=True, methods=["put"])
    def status(self, request, pk=None):
        serializer = AdminAccountStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.set_admin_account_status(
            user=self.get_object(),
            actor=request.user,
            new_status=serializer.validated_data["status"],
            expected_version=serializer.validated_data["version"],
        )
        return Response(AdminAccountDetailSerializer(user, context={"request": request}).data)

    @extend_schema(
        tags=["admin-accounts"],
        request=None,
        responses={200: AdminAccountCreateResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="temporary-password")
    def temporary_password(self, request, pk=None):
        user = self.get_object()
        password, _issued_at, expires_at = services.issue_temporary_password(
            user=user, actor=request.user
        )
        payload = {
            "account": AdminAccountDetailSerializer(
                User.objects.get(pk=user.pk), context={"request": request}
            ).data,
            "temporary_password": password,
            "temporary_password_expires_at": expires_at,
        }
        return Response(payload)

    @extend_schema(tags=["admin-accounts"], responses={200: AccountCourseSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def courses(self, request, pk=None):
        user = self.get_object()
        data = AdminAccountDetailSerializer(user).get_courses(user)
        return Response(data)

    @extend_schema(
        tags=["admin-accounts"],
        request=TeachingCoursesUpdateSerializer,
        responses={200: AccountCourseSerializer(many=True)},
    )
    @action(detail=True, methods=["put"], url_path="teaching-courses")
    def teaching_courses(self, request, pk=None):
        from apps.academics.models import Course

        serializer = TeachingCoursesUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = serializer.validated_data
        courses = list(Course.objects.filter(pk__in=fields["course_ids"]))
        main_courses = list(Course.objects.filter(pk__in=fields["main_course_ids"]))
        user = services.replace_teaching_courses(
            user=self.get_object(),
            actor=request.user,
            courses=courses,
            main_courses=main_courses,
            expected_version=fields["version"],
        )
        data = AdminAccountDetailSerializer(user).get_courses(user)
        return Response(data)

    @extend_schema(tags=["admin-accounts"], responses={200: AccountActivitySerializer(many=True)})
    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        from apps.audit.models import AuditLog

        user = self.get_object()
        queryset = AuditLog.objects.filter(entity_type="account", entity_id=user.pk)
        page = self.paginate_queryset(queryset)
        serializer = AccountActivitySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


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

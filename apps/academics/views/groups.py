"""Study group'lar va ulardagi studentlar."""

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.serializers import UserBriefSerializer
from common.constants import UUID_REGEX
from common.permissions import IsSuperAdmin

from .. import selectors, services
from ..filters import (
    GroupDirectoryFilter,
)
from ..models import GroupStudent, StudyGroup
from ..serializers import (
    GroupDetailSerializer,
    GroupDirectorySummarySerializer,
    GroupDirectoryWriteSerializer,
    GroupSerializer,
    GroupStatusSerializer,
    GroupStudentCreateSerializer,
    GroupStudentSerializer,
    GroupUpdateSerializer,
    GroupWriteSerializer,
)
from ._base import COURSE_PK, CourseNestedMixin


# StudyGroup: /courses/{course_pk}/groups
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["groups"], parameters=[COURSE_PK]),
    retrieve=extend_schema(tags=["groups"], parameters=[COURSE_PK]),
    create=extend_schema(
        tags=["groups"],
        parameters=[COURSE_PK],
        request=GroupWriteSerializer,
        responses={201: GroupSerializer},
    ),
    partial_update=extend_schema(
        tags=["groups"],
        parameters=[COURSE_PK],
        request=GroupWriteSerializer,
        responses={200: GroupSerializer},
    ),
    destroy=extend_schema(
        tags=["groups"],
        parameters=[COURSE_PK],
        responses={204: OpenApiResponse(description="Guruh o‘chirildi.")},
    ),
)
class GroupViewSet(
    CourseNestedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Guruhlar. O‘qish — Super Admin va kursga biriktirilgan teacher; yozish — Super Admin."""

    serializer_class = GroupSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StudyGroup.objects.none()
        return selectors.course_groups(self.get_course())

    def _group_response(self, group_id, status_code=status.HTTP_200_OK) -> Response:
        group = selectors.course_groups(self.get_course()).get(pk=group_id)
        return Response(GroupSerializer(group).data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = GroupWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = services.create_group(course=self.get_course(), **serializer.validated_data)
        return self._group_response(group.pk, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        group = self.get_object()
        serializer = GroupWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_group(group, **serializer.validated_data)
        return self._group_response(group.pk)

    def destroy(self, request, *args, **kwargs):
        services.delete_group(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["groups"], request=None, responses={200: GroupSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, *args, **kwargs):
        group = services.archive_group(self.get_object())
        return self._group_response(group.pk)

    @extend_schema(tags=["groups"], request=None, responses={200: GroupSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, *args, **kwargs):
        group = services.restore_group(self.get_object())
        return self._group_response(group.pk)


@extend_schema_view(
    list=extend_schema(tags=["group-directory"]),
    retrieve=extend_schema(tags=["group-directory"]),
    create=extend_schema(
        tags=["group-directory"],
        request=GroupDirectoryWriteSerializer,
        responses={201: GroupSerializer},
    ),
    partial_update=extend_schema(
        tags=["group-directory"],
        request=GroupUpdateSerializer,
        responses={200: GroupDetailSerializer},
    ),
)
class GroupDirectoryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    filterset_class = GroupDirectoryFilter
    search_fields = ["name", "course__name"]
    ordering_fields = ["name", "created_at", "students_count", "course__name"]
    ordering = ["name", "created_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsSuperAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StudyGroup.objects.none()
        return selectors.visible_group_directory(self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return GroupDirectoryWriteSerializer
        if self.action == "partial_update":
            return GroupUpdateSerializer
        if self.action == "retrieve":
            return GroupDetailSerializer
        return GroupSerializer

    def _group_response(self, group_id, status_code=status.HTTP_200_OK) -> Response:
        group = selectors.group_directory().get(pk=group_id)
        return Response(
            GroupDetailSerializer(group, context={"request": self.request}).data,
            status=status_code,
        )

    def create(self, request, *args, **kwargs):
        serializer = GroupDirectoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = services.create_group(**serializer.validated_data)
        return self._group_response(group.pk, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        group = self.get_object()
        serializer = GroupUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_group(group, **serializer.validated_data)
        return self._group_response(group.pk)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT")

    @extend_schema(
        tags=["group-directory"],
        request=GroupStatusSerializer,
        responses={200: GroupDetailSerializer},
    )
    @action(detail=True, methods=["put"], url_path="status")
    def set_status(self, request, pk=None):
        serializer = GroupStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = services.set_group_status(self.get_object(), **serializer.validated_data)
        return self._group_response(group.pk)

    @extend_schema(
        tags=["group-directory"],
        parameters=[OpenApiParameter("q", OpenApiTypes.STR)],
        responses={200: UserBriefSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="eligible-students")
    def eligible_students(self, request, pk=None):
        # `q` student qidiruvi; group queryset filteriga tushib 404 qilmasligi kerak.
        group = get_object_or_404(self.get_queryset(), pk=pk)
        queryset = selectors.eligible_group_students(group)
        query = request.query_params.get("q") or request.query_params.get("search")
        if query:
            queryset = queryset.filter(Q(full_name__icontains=query) | Q(email__icontains=query))
        page = self.paginate_queryset(queryset)
        serializer = UserBriefSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        tags=["group-directory"],
        request=GroupStudentCreateSerializer,
        responses={201: GroupStudentSerializer},
    )
    @action(detail=True, methods=["post"], url_path="students")
    def add_student(self, request, pk=None):
        serializer = GroupStudentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.add_student_to_group(
            group=self.get_object(), student=serializer.validated_data["student"]
        )
        return Response(GroupStudentSerializer(membership).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["group-directory"],
        responses={204: OpenApiResponse(description="Student guruhdan chiqarildi.")},
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=rf"students/(?P<student_id>{UUID_REGEX})",
    )
    def remove_student(self, request, pk=None, student_id=None):
        membership = get_object_or_404(
            selectors.group_students(self.get_object()), student_id=student_id
        )
        services.remove_student_from_group(group_student=membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["group-directory"], request=None, responses={200: GroupSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        group = services.archive_group(self.get_object())
        return self._group_response(group.pk)

    @extend_schema(tags=["group-directory"], request=None, responses={200: GroupSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        group = services.restore_group(self.get_object())
        return self._group_response(group.pk)

    @extend_schema(tags=["group-directory"], responses={200: GroupDirectorySummarySerializer})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(selectors.group_directory_summary())


# --------------------------------------------------------------------------
# GroupStudent: /courses/{course_pk}/groups/{group_pk}/students
# --------------------------------------------------------------------------
GROUP_PK = OpenApiParameter(
    "group_pk", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Guruh ID si"
)


@extend_schema_view(
    list=extend_schema(tags=["groups"], parameters=[COURSE_PK, GROUP_PK]),
    create=extend_schema(
        tags=["groups"],
        parameters=[COURSE_PK, GROUP_PK],
        request=GroupStudentCreateSerializer,
        responses={201: GroupStudentSerializer},
    ),
    destroy=extend_schema(
        tags=["groups"],
        parameters=[
            COURSE_PK,
            GROUP_PK,
            OpenApiParameter(
                "student_id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Student ID si"
            ),
        ],
        responses={204: OpenApiResponse(description="Student guruhdan chiqarildi.")},
    ),
)
class GroupStudentViewSet(
    CourseNestedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = GroupStudentSerializer
    search_fields = ["student__full_name", "student__email"]
    ordering_fields = ["added_at", "student__full_name"]
    ordering = ["-added_at"]
    lookup_field = "student_id"
    lookup_url_kwarg = "student_id"
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_group(self) -> StudyGroup:
        if not hasattr(self, "_group"):
            self._group = get_object_or_404(
                StudyGroup.objects.filter(course=self.get_course()), pk=self.kwargs["group_pk"]
            )
        return self._group

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GroupStudent.objects.none()
        return selectors.group_students(self.get_group())

    def create(self, request, *args, **kwargs):
        serializer = GroupStudentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.add_student_to_group(
            group=self.get_group(), student=serializer.validated_data["student"]
        )
        return Response(GroupStudentSerializer(membership).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        services.remove_student_from_group(group_student=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

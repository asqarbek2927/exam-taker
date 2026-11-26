"""Kurs modullari: /courses/{course_pk}/modules."""

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
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.constants import UUID_REGEX
from common.permissions import IsStudent, IsSuperAdmin, IsTeacher
from common.serializers import ArchivedResponseSerializer

from .. import selectors, services
from ..choices import ModuleStatus
from ..filters import (
    ModuleFilter,
)
from ..models import Module
from ..serializers import (
    ModuleOrderSerializer,
    ModuleSerializer,
    ModuleStatusSerializer,
    ModuleWithQuestionsSerializer,
    ModuleWriteSerializer,
)
from ._base import COURSE_PK, CourseNestedMixin


# --------------------------------------------------------------------------
# Module: /courses/{course_pk}/modules
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(
        tags=["modules"],
        parameters=[
            COURSE_PK,
            OpenApiParameter(
                "with_questions",
                OpenApiTypes.BOOL,
                description="`true` bo‘lsa har modul uchun savollar preview (faqat Teacher/Admin).",
            ),
        ],
        description="`status` berilmasa, `ARCHIVED` modullar ko‘rsatilmaydi.",
    ),
    retrieve=extend_schema(tags=["modules"], parameters=[COURSE_PK]),
    create=extend_schema(
        tags=["modules"],
        parameters=[COURSE_PK],
        request=ModuleWriteSerializer,
        responses={201: ModuleSerializer},
    ),
    partial_update=extend_schema(
        tags=["modules"],
        parameters=[COURSE_PK],
        request=ModuleWriteSerializer,
        responses={200: ModuleSerializer},
    ),
    destroy=extend_schema(
        tags=["modules"],
        parameters=[COURSE_PK],
        description=(
            "Bo‘sh va ishlatilmagan modul o‘chiriladi (204). Savollar yoki imtihonlar "
            'bog‘langan bo‘lsa — `ARCHIVED` holatiga o‘tadi (200, `{"archived": true}`).'
        ),
        responses={
            204: OpenApiResponse(description="Modul o‘chirildi."),
            200: ArchivedResponseSerializer,
        },
    ),
)
class ModuleViewSet(
    CourseNestedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Modullar course ichida shared: kursga biriktirilgan har qanday teacher tahrirlaydi."""

    read_permission = IsAuthenticated  # student ham o‘z kursining modullarini ko‘radi
    write_permission = IsSuperAdmin | IsTeacher
    filterset_class = ModuleFilter
    search_fields = ["title", "description"]
    ordering_fields = ["position", "title", "created_at"]
    ordering = ["position", "created_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def _wants_preview(self) -> bool:
        flag = self.request.query_params.get("with_questions", "").lower() in ("1", "true")
        return flag and not IsStudent().has_permission(self.request, self)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Module.objects.none()
        queryset = selectors.course_modules(
            self.get_course(),
            with_question_preview=self.action == "list" and self._wants_preview(),
        )
        if self.action == "list" and "status" not in self.request.query_params:
            queryset = queryset.exclude(status=ModuleStatus.ARCHIVED)
        return queryset

    def get_serializer_class(self):
        if self.action == "list" and self._wants_preview():
            return ModuleWithQuestionsSerializer
        return ModuleSerializer

    def _module_response(self, module_id, status_code=status.HTTP_200_OK) -> Response:
        module = selectors.course_modules(self.get_course()).get(pk=module_id)
        return Response(ModuleSerializer(module).data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = ModuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        module = services.create_module(course=self.get_course(), **serializer.validated_data)
        return self._module_response(module.pk, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        module = self.get_object()
        serializer = ModuleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_module(module, **serializer.validated_data)
        return self._module_response(module.pk)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT")

    def destroy(self, request, *args, **kwargs):
        archived = services.delete_or_archive_module(self.get_object())
        if archived:
            return Response({"archived": True}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["modules"], request=ModuleStatusSerializer, responses={200: ModuleSerializer}
    )
    @action(detail=True, methods=["put"], url_path="status")
    def set_status(self, request, *args, **kwargs):
        serializer = ModuleStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        module = services.set_module_status(self.get_object(), **serializer.validated_data)
        return self._module_response(module.pk)

    @extend_schema(
        tags=["modules"],
        request=ModuleOrderSerializer,
        responses={200: ModuleSerializer(many=True)},
    )
    @action(detail=False, methods=["put"], url_path="order")
    def order(self, request, *args, **kwargs):
        serializer = ModuleOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reorder_modules(course=self.get_course(), **serializer.validated_data)
        modules = selectors.course_modules(self.get_course())
        return Response(ModuleSerializer(modules, many=True).data)

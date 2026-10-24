from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.constants import UUID_REGEX
from common.permissions import IsCreatorOrSuperAdmin, IsSuperAdmin, IsTeacher
from common.serializers import ArchivedResponseSerializer

from . import selectors, services
from .choices import ExamStatus
from .filters import ExamFilter
from .models import Exam
from .serializers import (
    ExamCreateSerializer,
    ExamDetailSerializer,
    ExamDuplicateResponseSerializer,
    ExamListSerializer,
    ExamUpdateSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["exams"],
        parameters=[
            OpenApiParameter(
                "creator_ids",
                OpenApiTypes.STR,
                description="Muallif ID lari: takroriy parametr yoki vergul bilan.",
            )
        ],
        description="Exam Library. `status` berilmasa, `ARCHIVED` imtihonlar ko‘rsatilmaydi.",
        responses={200: ExamListSerializer(many=True)},
    ),
    retrieve=extend_schema(tags=["exams"], responses={200: ExamDetailSerializer}),
    create=extend_schema(
        tags=["exams"], request=ExamCreateSerializer, responses={201: ExamDetailSerializer}
    ),
    partial_update=extend_schema(
        tags=["exams"], request=ExamUpdateSerializer, responses={200: ExamDetailSerializer}
    ),
    destroy=extend_schema(
        tags=["exams"],
        description=(
            "Assignment tarixi bo‘lmagan imtihon o‘chiriladi (204); aks holda "
            '`ARCHIVED` (200, `{"archived": true}`).'
        ),
        responses={
            204: OpenApiResponse(description="Imtihon o‘chirildi."),
            200: ArchivedResponseSerializer,
        },
    ),
)
class ExamViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Imtihonlar kutubxonasi. Tahrirlash/o‘chirish — muallif yoki Super Admin;
    `duplicate` — kursga biriktirilgan har qanday teacher."""

    filterset_class = ExamFilter
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "title"]
    ordering = ["-created_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        role = (IsSuperAdmin | IsTeacher)()
        if self.action == "duplicate":
            return [role]
        return [role, IsCreatorOrSuperAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Exam.objects.none()
        if self.action == "list":
            queryset = selectors.exam_list(self.request.user)
            if "status" not in self.request.query_params:
                queryset = queryset.exclude(status=ExamStatus.ARCHIVED)
            return queryset
        return selectors.exam_detail(selectors.exams_visible_to(self.request.user))

    def get_serializer_class(self):
        return ExamListSerializer if self.action == "list" else ExamDetailSerializer

    def _detail(self, exam_id) -> dict:
        exam = selectors.exam_detail(Exam.objects.all()).get(pk=exam_id)
        return ExamDetailSerializer(exam).data

    def create(self, request, *args, **kwargs):
        serializer = ExamCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = services.create_exam(user=request.user, **serializer.validated_data)
        return Response(self._detail(exam.pk), status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        exam = self.get_object()
        serializer = ExamUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_exam(exam=exam, **serializer.validated_data)
        return Response(self._detail(exam.pk))

    def destroy(self, request, *args, **kwargs):
        archived = services.delete_or_archive_exam(self.get_object())
        if archived:
            return Response({"archived": True}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["exams"], request=None, responses={200: ExamDetailSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        exam = services.archive_exam(self.get_object())
        return Response(self._detail(exam.pk))

    @extend_schema(
        tags=["exams"],
        request=None,
        description=(
            "Imtihon nusxasi (yangi muallif, DRAFT). Arxivlangan modul/savollar o‘tkazilmaydi — "
            "ular `skipped_question_ids` da qaytadi."
        ),
        responses={201: ExamDuplicateResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        copy, skipped = services.duplicate_exam(user=request.user, exam=self.get_object())
        data = {**self._detail(copy.pk), "skipped_question_ids": skipped}
        return Response(data, status=status.HTTP_201_CREATED)

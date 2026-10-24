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
from .choices import QuestionStatus
from .filters import QuestionFilter
from .models import Question
from .serializers import (
    QuestionCreateSerializer,
    QuestionDetailSerializer,
    QuestionListSerializer,
    QuestionUpdateSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["questions"],
        parameters=[
            OpenApiParameter(
                "creator_ids",
                OpenApiTypes.STR,
                description="Muallif ID lari: takroriy parametr yoki vergul bilan.",
            )
        ],
        description="`status` berilmasa, `ARCHIVED` savollar ko‘rsatilmaydi.",
        responses={200: QuestionListSerializer(many=True)},
    ),
    retrieve=extend_schema(tags=["questions"], responses={200: QuestionDetailSerializer}),
    create=extend_schema(
        tags=["questions"],
        request=QuestionCreateSerializer,
        responses={201: QuestionDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["questions"],
        request=QuestionUpdateSerializer,
        responses={200: QuestionDetailSerializer},
    ),
    destroy=extend_schema(
        tags=["questions"],
        description=(
            "Imtihonda ishlatilmagan savol o‘chiriladi (204). Ishlatilgan bo‘lsa — "
            '`ARCHIVED` (200, `{"archived": true}`).'
        ),
        responses={
            204: OpenApiResponse(description="Savol o‘chirildi."),
            200: ArchivedResponseSerializer,
        },
    ),
)
class QuestionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Savollar banki. Teacher boshqa teacher savolini ko‘radi, lekin o‘zgartira olmaydi."""

    filterset_class = QuestionFilter
    search_fields = ["text"]
    ordering_fields = ["created_at", "default_points", "type"]
    ordering = ["-created_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        return [(IsSuperAdmin | IsTeacher)(), IsCreatorOrSuperAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Question.objects.none()
        if self.action == "list":
            queryset = selectors.question_list(self.request.user)
            if "status" not in self.request.query_params:
                queryset = queryset.exclude(status=QuestionStatus.ARCHIVED)
            return queryset
        return selectors.with_options(selectors.questions_visible_to(self.request.user))

    def get_serializer_class(self):
        return QuestionListSerializer if self.action == "list" else QuestionDetailSerializer

    def _detail_response(self, question_id, status_code=status.HTTP_200_OK) -> Response:
        question = selectors.with_options(Question.objects.all()).get(pk=question_id)
        return Response(QuestionDetailSerializer(question).data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = QuestionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = services.create_question(user=request.user, **serializer.validated_data)
        return self._detail_response(question.pk, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        question = self.get_object()
        serializer = QuestionUpdateSerializer(question, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_question(question=question, **serializer.validated_data)
        return self._detail_response(question.pk)

    def destroy(self, request, *args, **kwargs):
        archived = services.delete_or_archive_question(self.get_object())
        if archived:
            return Response({"archived": True}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["questions"], request=None, responses={200: QuestionDetailSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        question = services.archive_question(self.get_object())
        return self._detail_response(question.pk)

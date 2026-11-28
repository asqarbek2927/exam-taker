from django.db import transaction
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit
from common.constants import UUID_REGEX
from common.permissions import IsCreatorOrSuperAdmin, IsSuperAdmin, IsTeacher
from common.serializers import ArchivedResponseSerializer

from . import selectors, services
from .choices import QuestionStatus
from .filters import QuestionFilter
from .json_import import build_question_import_json_template, parse_question_import_json
from .models import Question
from .serializers import (
    QuestionBankSummarySerializer,
    QuestionCreateSerializer,
    QuestionDetailSerializer,
    QuestionImportContextSerializer,
    QuestionImportFileSerializer,
    QuestionImportResponseSerializer,
    QuestionImportTemplateQuerySerializer,
    QuestionListSerializer,
    QuestionUpdateSerializer,
)
from .xlsx import QuestionXLSXError, build_question_import_template, parse_question_import


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

    @extend_schema(
        tags=["questions"],
        responses={200: QuestionBankSummarySerializer},
        description="Role doirasidagi question bank statistika kartalari.",
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        data = selectors.question_bank_summary(request.user)
        return Response(QuestionBankSummarySerializer(data).data)

    @extend_schema(
        tags=["questions"],
        parameters=[QuestionImportTemplateQuerySerializer],
        responses={
            (
                200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ): OpenApiTypes.BINARY
        },
        description="Tanlangan kurs va modul ma'lumotlari yozilgan XLSX import shabloni.",
    )
    @action(detail=False, methods=["get"], url_path="import-template")
    def import_template(self, request):
        serializer = QuestionImportTemplateQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        course = serializer.validated_data["course"]
        module = serializer.validated_data["module"]
        services.validate_question_context(user=request.user, course=course, module=module)
        content = build_question_import_template(course=course, module=module)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="questions-{course.id}-{module.id}.xlsx"'
        )
        return response

    @extend_schema(
        tags=["questions"],
        parameters=[QuestionImportTemplateQuerySerializer],
        responses={(200, "application/json"): OpenApiTypes.BINARY},
        description=(
            "Tanlangan kurs va modul ma'lumotlari yozilgan JSON import shabloni (XLSX shablonning "
            "JSON varianti): `course`, `module`, AI uchun `instructions`, `example_questions` va "
            "to'ldiriladigan bo'sh `questions` ro'yxati."
        ),
    )
    @action(detail=False, methods=["get"], url_path="import-template-json")
    def import_template_json(self, request):
        serializer = QuestionImportTemplateQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        course = serializer.validated_data["course"]
        module = serializer.validated_data["module"]
        services.validate_question_context(user=request.user, course=course, module=module)
        content = build_question_import_json_template(course=course, module=module)
        response = HttpResponse(content, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="questions-{course.id}-{module.id}.json"'
        )
        return response

    @extend_schema(
        tags=["questions"],
        request=QuestionImportFileSerializer,
        responses={201: QuestionImportResponseSerializer},
        description=(
            "XLSX yoki JSON fayl ichidagi barcha savollarni atomik tarzda question bankka import "
            "qiladi. Format fayl kengaytmasidan aniqlanadi (`.xlsx` / `.json`)."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_xlsx(self, request):
        upload = QuestionImportFileSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        upload_file = upload.validated_data["file"]
        parser = (
            parse_question_import_json
            if upload_file.name.lower().endswith(".json")
            else parse_question_import
        )
        try:
            parsed = parser(upload_file)
        except QuestionXLSXError as exc:
            raise serializers.ValidationError({"file": exc.messages}) from exc

        context = QuestionImportContextSerializer(
            data={"course_id": parsed.course_id, "module_id": parsed.module_id}
        )
        if not context.is_valid():
            # Kalitlar (`course_id` / `module_id`) o‘zgarmaydi — faqat tushunarli matn.
            hint = "Shablonni `import-template` orqali shu kurs uchun qayta yuklab oling."
            labels = {"course_id": "Kurs", "module_id": "Modul"}
            raise serializers.ValidationError(
                {
                    key: [f"Fayldagi {labels.get(key, key)} ID topilmadi. {hint}"]
                    for key in context.errors
                }
            )
        course = context.validated_data["course"]
        module = context.validated_data["module"]
        services.validate_question_context(user=request.user, course=course, module=module)

        validated_questions = []
        row_errors = []
        for item in parsed.questions:
            question = QuestionCreateSerializer(
                data={
                    "course_id": str(course.id),
                    "module_id": str(module.id),
                    **item.data,
                }
            )
            if question.is_valid():
                validated_questions.append(question.validated_data)
            else:
                row_errors.append({"row": item.row, "errors": question.errors})
        if row_errors:
            raise serializers.ValidationError({"rows": row_errors})

        with transaction.atomic():
            created = services.import_questions(user=request.user, questions=validated_questions)
            record_audit(
                actor=request.user,
                action=AuditAction.QUESTIONS_IMPORTED,
                entity_type="module",
                entity_id=module.pk,
                metadata={
                    "course_id": course.pk,
                    "module_id": module.pk,
                    "count": len(created),
                    "format": "json" if upload_file.name.lower().endswith(".json") else "xlsx",
                    "file_name": upload_file.name[:200],
                },
            )
        response_data = {
            "created_count": len(created),
            "course_id": course.id,
            "module_id": module.id,
            "question_ids": [question.id for question in created],
        }
        return Response(
            QuestionImportResponseSerializer(response_data).data,
            status=status.HTTP_201_CREATED,
        )

    def create(self, request, *args, **kwargs):
        serializer = QuestionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = services.create_question(user=request.user, **serializer.validated_data)
        return self._detail_response(question.pk, status.HTTP_201_CREATED)

    def _audit(self, question: Question, action: str, *, entity_id=None, **metadata) -> None:
        record_audit(
            actor=self.request.user,
            action=action,
            entity_type="question",
            entity_id=entity_id or question.pk,
            metadata={
                "course_id": question.course_id,
                "module_id": question.module_id,
                "type": question.type,
                "question_text": question.text[:200],
                **metadata,
            },
        )

    def partial_update(self, request, *args, **kwargs):
        question = self.get_object()
        serializer = QuestionUpdateSerializer(question, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            services.update_question(question=question, **serializer.validated_data)
            # Faqat o'zgargan maydon nomlari; "options" — variantlar yoki to'g'ri javob o'zgargan.
            self._audit(
                question,
                AuditAction.QUESTION_UPDATED,
                changed_fields=sorted(serializer.validated_data),
            )
        return self._detail_response(question.pk)

    def destroy(self, request, *args, **kwargs):
        question = self.get_object()
        question_id = question.pk  # butunlay o'chirilsa Django pk ni None qiladi
        with transaction.atomic():
            archived = services.delete_or_archive_question(question)
            self._audit(
                question, AuditAction.QUESTION_DELETED, entity_id=question_id, archived=archived
            )
        if archived:
            return Response({"archived": True}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["questions"], request=None, responses={200: QuestionDetailSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        with transaction.atomic():
            question = services.archive_question(self.get_object())
            self._audit(question, AuditAction.QUESTION_DELETED, archived=True)
        return self._detail_response(question.pk)

    @extend_schema(tags=["questions"], request=None, responses={200: QuestionDetailSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        with transaction.atomic():
            question = services.restore_question(self.get_object())
            self._audit(question, AuditAction.QUESTION_RESTORED)
        return self._detail_response(question.pk)

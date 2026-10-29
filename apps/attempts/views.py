from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.choices import UserRole
from common.constants import UUID_REGEX
from common.permissions import IsStudent, IsSuperAdmin, IsTeacher

from . import selectors, services
from .choices import AttemptStatus
from .filters import AttemptFilter, PendingGradingFilter
from .models import ExamAttempt, StudentAnswer
from .serializers import (
    AnswerInputSerializer,
    AnswerSerializer,
    AttemptEventInputSerializer,
    AttemptEventResponseSerializer,
    AttemptListSerializer,
    AttemptResultSerializer,
    AttemptStaffDetailSerializer,
    GradeInputSerializer,
    GradeResponseSerializer,
    PendingAttemptSerializer,
    StudentAttemptSerializer,
)

EXAM_QUESTION_REGEX = UUID_REGEX


@extend_schema_view(
    list=extend_schema(
        tags=["attempts"],
        description=(
            "Role bo‘yicha: Student — o‘ziniki, Teacher — o‘z kurslari, Super Admin — hammasi. "
            "Muddati o‘tgan faol attemptlar ro‘yxat olinishida avtomatik yopiladi."
        ),
        responses={200: AttemptListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["attempts"],
        description=(
            "Student: faol attempt — savollar+javoblar+taymer; yakunlangan — faqat natija "
            "(to‘g‘ri javoblarsiz). Teacher/Admin: javoblar va to‘g‘ri variantlar bilan."
        ),
        responses={
            200: PolymorphicProxySerializer(
                component_name="AttemptDetail",
                serializers=[
                    StudentAttemptSerializer,
                    AttemptResultSerializer,
                    AttemptStaffDetailSerializer,
                ],
                resource_type_field_name=None,
            )
        },
    ),
)
class AttemptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    filterset_class = AttemptFilter
    search_fields = ["student__full_name", "student__email", "assignment__exam__title"]
    ordering_fields = ["started_at", "submitted_at", "score", "percentage"]
    ordering = ["-started_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "put", "head", "options"]

    def get_permissions(self):
        if self.action in ("save_answer", "submit", "events"):
            return [IsStudent()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExamAttempt.objects.none()
        return selectors.attempts_visible_to(self.request.user)

    def get_serializer_class(self):
        return AttemptListSerializer

    # --- list / retrieve (lazy finalization) ---------------------------
    def list(self, request, *args, **kwargs):
        services.finalize_expired_attempts(self.get_queryset(), limit=200)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        attempt = self.get_object()
        services.finalize_if_expired(attempt.pk)
        attempt = self.get_queryset().get(pk=attempt.pk)  # yangilangan holat
        if request.user.role == UserRole.STUDENT:
            if attempt.status == AttemptStatus.IN_PROGRESS:
                return Response(StudentAttemptSerializer(attempt).data)
            attempt = selectors.with_answers(self.get_queryset()).get(pk=attempt.pk)
            return Response(AttemptResultSerializer(attempt).data)
        attempt = selectors.with_answers(self.get_queryset()).get(pk=attempt.pk)
        return Response(AttemptStaffDetailSerializer(attempt).data)

    # --- autosave ------------------------------------------------------
    @extend_schema(
        tags=["attempts"],
        parameters=[
            OpenApiParameter(
                "exam_question_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="ExamQuestion ID si (student DTO dagi savol `id` si)",
            )
        ],
        request=AnswerInputSerializer,
        responses={200: AnswerSerializer},
    )
    @action(
        detail=True,
        methods=["put"],
        url_path=rf"answers/(?P<exam_question_id>{EXAM_QUESTION_REGEX})",
    )
    def save_answer(self, request, pk=None, exam_question_id=None):
        serializer = AnswerInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answer = services.save_answer(
            student=request.user,
            attempt_id=pk,
            exam_question_id=exam_question_id,
            option_ids=serializer.validated_data.get("option_ids"),
            text_answer=serializer.validated_data.get("text_answer"),
            revision=serializer.validated_data.get("revision"),
        )
        return Response(AnswerSerializer(answer).data)

    # --- browser integrity events ------------------------------------
    @extend_schema(
        tags=["attempts"],
        request=AttemptEventInputSerializer,
        responses={200: AttemptEventResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def events(self, request, pk=None):
        serializer = AttemptEventInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event, attempt, event_action = services.record_attempt_event(
            student=request.user,
            attempt_id=pk,
            event_type=serializer.validated_data["type"],
            event_id=serializer.validated_data["event_id"],
            client_at=serializer.validated_data["client_at"],
            details=serializer.validated_data["details"],
        )
        payload = {
            "event_id": event.event_id,
            "focus_violations": attempt.focus_violations,
            "threshold": services.FOCUS_VIOLATION_THRESHOLD,
            "action": event_action,
            "status": attempt.status,
            "submission_reason": attempt.finalization_reason,
        }
        return Response(AttemptEventResponseSerializer(payload).data)

    # --- submit --------------------------------------------------------
    @extend_schema(tags=["attempts"], request=None, responses={200: AttemptResultSerializer})
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        attempt = services.submit_attempt(student=request.user, attempt_id=pk)
        attempt = self.get_queryset().get(pk=attempt.pk)
        return Response(AttemptResultSerializer(attempt).data, status=status.HTTP_200_OK)


# --------------------------------------------------------------------------
# Manual grading (TZ 11.7)
# --------------------------------------------------------------------------
@extend_schema(
    tags=["grading"],
    description=(
        "Qo‘lda baholashni kutayotgan attemptlar (eng eskisi birinchi). Teacher — biriktirilgan "
        "kurslar, Super Admin — hammasi. Muddati o‘tgan faol attemptlar avtomatik yopiladi."
    ),
)
class PendingGradingView(generics.ListAPIView):
    permission_classes = [(IsSuperAdmin | IsTeacher)]
    serializer_class = PendingAttemptSerializer
    filterset_class = PendingGradingFilter
    search_fields = ["student__full_name", "student__email", "assignment__exam__title"]
    ordering_fields = ["submitted_at", "started_at"]
    ordering = ["submitted_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExamAttempt.objects.none()
        return selectors.attempts_visible_to(self.request.user).annotate(
            pending_answers_count=Count("answers", filter=Q(answers__points_awarded__isnull=True))
        )

    def list(self, request, *args, **kwargs):
        services.finalize_expired_attempts(selectors.attempts_visible_to(request.user), limit=200)
        return super().list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = queryset.filter(status=AttemptStatus.PENDING_GRADING)
        return super().filter_queryset(queryset)


@extend_schema(
    tags=["grading"],
    request=GradeInputSerializer,
    responses={200: GradeResponseSerializer},
    description=(
        "OPEN_ENDED javobni baholaydi. Hamma javob baholangach attempt `GRADED` bo‘ladi va "
        "`score/percentage/passed` hisoblanadi. Baholangan javobni qayta baholash mumkin."
    ),
)
class AnswerGradeView(APIView):
    permission_classes = [(IsSuperAdmin | IsTeacher)]

    def patch(self, request, answer_id):
        answer = get_object_or_404(
            StudentAnswer.objects.filter(attempt__in=selectors.attempts_visible_to(request.user)),
            pk=answer_id,
        )
        serializer = GradeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answer, attempt = services.grade_answer(
            grader=request.user, answer=answer, **serializer.validated_data
        )
        answer = (
            StudentAnswer.objects.select_related("exam_question__question", "graded_by")
            .prefetch_related("selected_options", "exam_question__question__options")
            .get(pk=answer.pk)
        )
        return Response(
            GradeResponseSerializer({"answer": answer, "attempt": attempt}).data,
            status=status.HTTP_200_OK,
        )

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attempts import services as attempt_services
from apps.attempts.models import ExamAttempt
from apps.attempts.serializers import StudentAttemptSerializer
from apps.users.choices import UserRole
from common.constants import UUID_REGEX
from common.permissions import IsCreatorOrSuperAdmin, IsStudent, IsSuperAdmin, IsTeacher

from . import selectors, services
from .filters import AssignmentFilter
from .models import ExamAssignment
from .serializers import (
    AssignmentCreateSerializer,
    AssignmentDetailSerializer,
    AssignmentSerializer,
    AssignmentSummarySerializer,
    AssignmentUpdateSerializer,
    StudentAssignmentSerializer,
)

TRANSITION_ACTIONS = tuple(services.TRANSITIONS)


@extend_schema_view(
    list=extend_schema(
        tags=["exam-assignments"],
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                description="Hisoblangan holat: DRAFT/SCHEDULED/ACTIVE/PAUSED/COMPLETED/CANCELLED.",
            )
        ],
        description=(
            "Role bo‘yicha: Super Admin — hammasi; Teacher — biriktirilgan kurslar; "
            "Student — faqat o‘ziga eligible (DRAFT/CANCELLED yashirin) va o‘z "
            "statistikasi bilan"
        ),
        responses={200: AssignmentSerializer(many=True)},
    ),
    retrieve=extend_schema(tags=["exam-assignments"], responses={200: AssignmentDetailSerializer}),
    create=extend_schema(
        tags=["exam-assignments"],
        request=AssignmentCreateSerializer,
        responses={201: AssignmentDetailSerializer},
    ),
    partial_update=extend_schema(
        tags=["exam-assignments"],
        request=AssignmentUpdateSerializer,
        responses={200: AssignmentDetailSerializer},
    ),
)
class AssignmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    filterset_class = AssignmentFilter
    search_fields = ["exam__title", "exam__course__name"]
    ordering_fields = ["start_at", "end_at", "created_at"]
    ordering = ["-start_at"]
    lookup_value_regex = UUID_REGEX
    owner_attr = "published_by_id"
    http_method_names = ["get", "post", "patch", "head", "options"]

    # --- permissions ---------------------------------------------------
    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        if self.action == "start":
            return [IsStudent()]
        role = (IsSuperAdmin | IsTeacher)()
        if self.action in ("create", "summary"):
            return [role]
        return [role, IsCreatorOrSuperAdmin()]

    # --- queryset / serializer ----------------------------------------
    def _is_student(self) -> bool:
        return self.request.user.role == UserRole.STUDENT

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExamAssignment.objects.none()
        user = self.request.user
        if user.role == UserRole.STUDENT:
            return selectors.student_assignments(user)
        qs = selectors.staff_visible(user)
        if self.action == "list" and "scope" not in self.request.query_params:
            qs = qs.filter(is_archived=False)
        return selectors.staff_assignments(qs)

    def get_serializer_class(self):
        if self._is_student():
            return StudentAssignmentSerializer
        return AssignmentSerializer if self.action == "list" else AssignmentDetailSerializer

    def _detail(self, assignment_id) -> dict:
        assignment = selectors.staff_assignments(ExamAssignment.objects.all()).get(pk=assignment_id)
        return AssignmentDetailSerializer(assignment).data

    @extend_schema(
        tags=["exam-assignments"],
        responses={200: AssignmentSummarySerializer},
        description="Role doirasidagi arxivlanmagan assignment kartochka hisoblari.",
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        data = selectors.assignment_directory_summary(request.user)
        return Response(AssignmentSummarySerializer(data).data)

    # --- list / retrieve (student uchun lazy finalization) -------------
    def list(self, request, *args, **kwargs):
        self._finalize_students_expired()
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        self._finalize_students_expired()
        return super().retrieve(request, *args, **kwargs)

    def _finalize_students_expired(self) -> None:
        """`can_start`/`attempts_used` to‘g‘ri bo‘lishi uchun muddati o‘tganlarini yopamiz."""
        if self._is_student():
            attempt_services.finalize_expired_attempts(
                ExamAttempt.objects.filter(student=self.request.user)
            )

    # --- create / update ----------------------------------------------
    def create(self, request, *args, **kwargs):
        serializer = AssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = services.create_assignment(user=request.user, **serializer.validated_data)
        return Response(self._detail(assignment.pk), status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        assignment = self.get_object()
        serializer = AssignmentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_assignment(assignment=assignment, **serializer.validated_data)
        return Response(self._detail(assignment.pk))

    # --- status amallari ----------------------------------------------
    def _transition(self, action_name: str) -> Response:
        assignment = services.transition(assignment=self.get_object(), action=action_name)
        return Response(self._detail(assignment.pk))

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._transition("publish")

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return self._transition("pause")

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._transition("resume")

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition("complete")

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition("cancel")

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._transition("restore")

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        assignment = services.archive_assignment(assignment=self.get_object())
        return Response(self._detail(assignment.pk))

    @extend_schema(
        tags=["exam-assignments"], request=None, responses={200: AssignmentDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        assignment = services.unarchive_assignment(assignment=self.get_object())
        return Response(self._detail(assignment.pk))

    # --- student: imtihonni boshlash ----------------------------------
    @extend_schema(
        tags=["exam-assignments"],
        request=None,
        description=(
            "Yangi attempt boshlaydi: savollar (to‘g‘ri javobsiz), `deadline_at`, "
            "`server_now`. Faol attempt bo‘lsa yoki limit tugagan bo‘lsa — 409."
        ),
        responses={201: StudentAttemptSerializer},
    )
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        assignment = self.get_object()  # eligible bo‘lmasa — 404
        attempt = attempt_services.start_attempt(student=request.user, assignment_id=assignment.pk)
        return Response(StudentAttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)

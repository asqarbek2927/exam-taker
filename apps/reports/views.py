from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attempts import services as attempt_services
from apps.attempts.models import ExamAttempt
from common.permissions import IsStudent, IsSuperAdmin, IsTeacher

from . import selectors
from .filters import ResultFilter
from .serializers import (
    AdminDashboardSerializer,
    ResultSerializer,
    ResultSummarySerializer,
    StudentDashboardSerializer,
    TeacherDashboardSerializer,
)


@extend_schema(
    tags=["results"],
    description=(
        "Yakunlangan attemptlar. Student — faqat o‘ziniki, Teacher — o‘z kurslari, "
        "Super Admin — hammasi. `latest_only=true` — har (assignment, student) uchun oxirgisi; "
        "`is_latest` — joriy natija shu attemptmi. `date_from/date_to` — sana (YYYY-MM-DD)."
    ),
)
class ResultListView(generics.ListAPIView):
    serializer_class = ResultSerializer
    filterset_class = ResultFilter
    search_fields = [
        "student__full_name",
        "student__email",
        "assignment__exam__title",
        "assignment__exam__course__name",
    ]
    ordering_fields = ["submitted_at", "percentage", "score", "attempt_number"]
    ordering = ["-submitted_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExamAttempt.objects.none()
        return selectors.result_list(self.request.user)

    def list(self, request, *args, **kwargs):
        # Muddati o‘tgan faol attemptlar natijaga kirishi uchun avval yopiladi (TZ 11.6).
        attempt_services.finalize_expired_attempts(
            selectors.attempts_visible_to(request.user), limit=200
        )
        return super().list(request, *args, **kwargs)


@extend_schema(
    tags=["results"],
    responses={200: ResultSummarySerializer},
    description=(
        "Results page kartalari va grading progress. List bilan bir xil filter/searchlarni oladi."
    ),
)
class ResultSummaryView(generics.GenericAPIView):
    serializer_class = ResultSummarySerializer
    filterset_class = ResultFilter
    search_fields = ResultListView.search_fields

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExamAttempt.objects.none()
        return selectors.results_visible_to(self.request.user)

    def get(self, request):
        attempt_services.finalize_expired_attempts(
            selectors.attempts_visible_to(request.user), limit=200
        )
        data = selectors.result_summary(self.filter_queryset(self.get_queryset()))
        return Response(ResultSummarySerializer(data).data)


class _DashboardView(APIView):
    def get(self, request):
        return Response(self.build(request.user))

    def build(self, user) -> dict:
        raise NotImplementedError


@extend_schema(tags=["dashboard"], responses={200: AdminDashboardSerializer})
class AdminDashboardView(_DashboardView):
    permission_classes = [IsSuperAdmin]

    def build(self, user):
        return selectors.admin_dashboard()


@extend_schema(tags=["dashboard"], responses={200: TeacherDashboardSerializer})
class TeacherDashboardView(_DashboardView):
    permission_classes = [IsTeacher]

    def build(self, user):
        attempt_services.finalize_expired_attempts(selectors.attempts_visible_to(user), limit=200)
        return selectors.teacher_dashboard(user)


@extend_schema(tags=["dashboard"], responses={200: StudentDashboardSerializer})
class StudentDashboardView(_DashboardView):
    permission_classes = [IsStudent]

    def build(self, user):
        attempt_services.finalize_expired_attempts(ExamAttempt.objects.filter(student=user))
        return selectors.student_dashboard(user)

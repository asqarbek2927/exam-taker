"""Kurslar, kurs teacher/student a'zoligi va studentning o'z kurslari."""

from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.constants import UUID_REGEX
from common.exceptions import BusinessRuleError
from common.permissions import IsStudent, IsSuperAdmin

from .. import selectors, services
from ..choices import CourseStatus, EnrollmentStatus
from ..filters import (
    CourseFilter,
    CourseTeacherFilter,
    EnrollmentFilter,
)
from ..models import CourseTeacher, Enrollment
from ..serializers import (
    AcademicStudentCourseCardSerializer,
    CourseCatalogSummarySerializer,
    CourseCreateSerializer,
    CourseDetailSerializer,
    CourseListSerializer,
    CourseMutationSerializer,
    CourseStatusSerializer,
    CourseTeacherCreateSerializer,
    CourseTeacherSerializer,
    CourseTeacherUpdateSerializer,
    EnrollmentCreateSerializer,
    EnrollmentSerializer,
    EnrollmentUpdateSerializer,
)
from ._base import COURSE_PK, CourseNestedMixin


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["courses"], responses={200: CourseListSerializer(many=True)}),
    retrieve=extend_schema(tags=["courses"], responses={200: CourseDetailSerializer}),
    create=extend_schema(
        tags=["courses"], request=CourseCreateSerializer, responses={201: CourseDetailSerializer}
    ),
    partial_update=extend_schema(
        tags=["courses"], request=CourseMutationSerializer, responses={200: CourseDetailSerializer}
    ),
)
class CourseViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Kurslar. O‘qish — rolga qarab scoped; yozish — faqat Super Admin."""

    filterset_class = CourseFilter
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name", "created_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsSuperAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return selectors.Course.objects.none()
        return selectors.with_course_stats(selectors.courses_visible_to(self.request.user))

    def get_serializer_class(self):
        if self.action == "list":
            return CourseListSerializer
        return CourseDetailSerializer

    def _detail_response(self, course_id, status_code=status.HTTP_200_OK) -> Response:
        # Qayta o‘qiladi: response `teachers_count`/`students_count` annotatsiyasini talab qiladi.
        course = selectors.course_detail_queryset().get(pk=course_id)
        return Response(
            CourseDetailSerializer(course, context={"request": self.request}).data,
            status=status_code,
        )

    def create(self, request, *args, **kwargs):
        serializer = CourseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "name" not in serializer.validated_data:
            raise ValidationError({"name": ["This field is required."]})
        course = services.create_course(**serializer.validated_data)
        return self._detail_response(course.pk, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        course = self.get_object()
        serializer = CourseMutationSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_course(course, **serializer.validated_data)
        return self._detail_response(course.pk)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT")

    @extend_schema(tags=["courses"], request=None, responses={200: CourseDetailSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        course = services.archive_course(self.get_object())
        return self._detail_response(course.pk)

    @extend_schema(tags=["courses"], request=None, responses={200: CourseDetailSerializer})
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        course = services.restore_course(self.get_object())
        return self._detail_response(course.pk)

    @extend_schema(
        tags=["courses"], request=CourseStatusSerializer, responses={200: CourseDetailSerializer}
    )
    @action(detail=True, methods=["put"], url_path="status")
    def set_status(self, request, pk=None):
        serializer = CourseStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = services.set_course_status(self.get_object(), **serializer.validated_data)
        return self._detail_response(course.pk)

    @extend_schema(tags=["courses"], responses={200: CourseCatalogSummarySerializer})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(selectors.course_catalog_summary())


@extend_schema_view(
    list=extend_schema(tags=["course-teachers"], parameters=[COURSE_PK]),
    create=extend_schema(
        tags=["course-teachers"],
        parameters=[COURSE_PK],
        request=CourseTeacherCreateSerializer,
        responses={201: CourseTeacherSerializer},
    ),
    partial_update=extend_schema(
        tags=["course-teachers"],
        parameters=[COURSE_PK],
        request=CourseTeacherUpdateSerializer,
        responses={200: CourseTeacherSerializer},
    ),
    destroy=extend_schema(
        tags=["course-teachers"],
        parameters=[COURSE_PK],
        responses={204: OpenApiResponse(description="Teacher kursdan olindi.")},
    ),
)
class CourseTeacherViewSet(
    CourseNestedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CourseTeacherSerializer
    filterset_class = CourseTeacherFilter
    search_fields = ["teacher__full_name", "teacher__email"]
    ordering_fields = ["assigned_at", "type"]
    ordering = ["type", "assigned_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CourseTeacher.objects.none()
        return selectors.course_teachers(self.get_course())

    def create(self, request, *args, **kwargs):
        serializer = CourseTeacherCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course_teacher = services.assign_teacher(
            course=self.get_course(),
            teacher=serializer.validated_data["teacher"],
            teacher_type=serializer.validated_data["type"],
        )
        return Response(
            CourseTeacherSerializer(course_teacher).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        course_teacher = self.get_object()
        serializer = CourseTeacherUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_teacher_type(
            course_teacher=course_teacher, teacher_type=serializer.validated_data["type"]
        )
        return Response(CourseTeacherSerializer(course_teacher).data)

    def destroy(self, request, *args, **kwargs):
        services.remove_teacher(course_teacher=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        tags=["course-students"],
        parameters=[COURSE_PK],
        description="`status` berilmasa, `REMOVED` holatdagilar ko‘rsatilmaydi.",
    ),
    create=extend_schema(
        tags=["course-students"],
        parameters=[COURSE_PK],
        request=EnrollmentCreateSerializer,
        responses={201: EnrollmentSerializer},
    ),
    partial_update=extend_schema(
        tags=["course-students"],
        parameters=[COURSE_PK],
        request=EnrollmentUpdateSerializer,
        responses={200: EnrollmentSerializer},
    ),
    destroy=extend_schema(
        tags=["course-students"],
        parameters=[COURSE_PK],
        responses={204: OpenApiResponse(description="Enrollment `REMOVED` holatiga o‘tdi.")},
    ),
)
class EnrollmentViewSet(
    CourseNestedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EnrollmentSerializer
    filterset_class = EnrollmentFilter
    search_fields = ["student__full_name", "student__email"]
    ordering_fields = ["enrolled_at", "student__full_name"]
    ordering = ["-enrolled_at"]
    lookup_value_regex = UUID_REGEX
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Enrollment.objects.none()
        queryset = selectors.course_enrollments(self.get_course())
        if self.action == "list" and "status" not in self.request.query_params:
            queryset = queryset.exclude(status=EnrollmentStatus.REMOVED)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = EnrollmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = services.enroll_student(
            course=self.get_course(), student=serializer.validated_data["student"]
        )
        return Response(EnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        enrollment = self.get_object()
        serializer = EnrollmentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_enrollment_status(
            enrollment=enrollment, status=serializer.validated_data["status"]
        )
        return Response(EnrollmentSerializer(enrollment).data)

    def destroy(self, request, *args, **kwargs):
        services.remove_enrollment(enrollment=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


class EnrollmentAliasViewSet(
    CourseNestedMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """TZ alias: enrollment student ID bilan oâ€˜chiriladi; eski `/students` saqlanadi."""

    serializer_class = EnrollmentSerializer
    lookup_field = "student_id"
    lookup_url_kwarg = "student_id"
    lookup_value_regex = UUID_REGEX
    http_method_names = ["post", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Enrollment.objects.none()
        return selectors.course_enrollments(self.get_course())

    @extend_schema(
        tags=["course-enrollments"],
        request=EnrollmentCreateSerializer,
        responses={200: EnrollmentSerializer, 201: EnrollmentSerializer},
    )
    def create(self, request, *args, **kwargs):
        course = self.get_course()
        if course.status != CourseStatus.ACTIVE:
            raise BusinessRuleError("Student faqat ACTIVE kursga yoziladi.")
        serializer = EnrollmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = serializer.validated_data["student"]
        existing = Enrollment.objects.filter(
            course=course, student=student, status=EnrollmentStatus.ACTIVE
        ).first()
        if existing is not None:
            return Response(EnrollmentSerializer(existing).data)
        enrollment = services.enroll_student(course=course, student=student)
        return Response(EnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["course-enrollments"], responses={204: None})
    def destroy(self, request, *args, **kwargs):
        services.remove_enrollment(enrollment=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentMyCoursesView(APIView):
    permission_classes = [IsStudent]

    @extend_schema(
        tags=["student-courses"], responses={200: AcademicStudentCourseCardSerializer(many=True)}
    )
    def get(self, request):
        queryset = selectors.with_course_stats(
            selectors.courses_visible_to(request.user).filter(
                enrollments__student=request.user,
                enrollments__status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED],
            )
        ).distinct()
        return Response(AcademicStudentCourseCardSerializer(queryset, many=True).data)

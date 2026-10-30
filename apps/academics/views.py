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
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.serializers import UserBriefSerializer
from common.constants import UUID_REGEX
from common.exceptions import BusinessRuleError
from common.permissions import IsStudent, IsSuperAdmin, IsTeacher
from common.serializers import ArchivedResponseSerializer

from . import selectors, services
from .choices import CourseStatus, EnrollmentStatus, ModuleStatus
from .filters import (
    CourseFilter,
    CourseTeacherFilter,
    EnrollmentFilter,
    GroupDirectoryFilter,
    ModuleFilter,
)
from .models import CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup
from .serializers import (
    AcademicStudentCourseCardSerializer,
    CourseCatalogSummarySerializer,
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
    GroupDetailSerializer,
    GroupDirectorySummarySerializer,
    GroupDirectoryWriteSerializer,
    GroupSerializer,
    GroupStatusSerializer,
    GroupStudentCreateSerializer,
    GroupStudentSerializer,
    GroupUpdateSerializer,
    GroupWriteSerializer,
    ModuleOrderSerializer,
    ModuleSerializer,
    ModuleStatusSerializer,
    ModuleWithQuestionsSerializer,
    ModuleWriteSerializer,
)

COURSE_PK = OpenApiParameter(
    "course_pk", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Kurs ID si"
)


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["courses"], responses={200: CourseListSerializer(many=True)}),
    retrieve=extend_schema(tags=["courses"], responses={200: CourseDetailSerializer}),
    create=extend_schema(
        tags=["courses"], request=CourseMutationSerializer, responses={201: CourseDetailSerializer}
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
        serializer = CourseMutationSerializer(data=request.data)
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


# --------------------------------------------------------------------------
# Nested: /courses/{course_pk}/...
# --------------------------------------------------------------------------
class CourseNestedMixin:
    """`/courses/{course_pk}/...` resurslari uchun umumiy mantiq.

    * Kurs foydalanuvchiga ko‘rinmasa — 404.
    * `read_permission` — `read_actions` uchun, `write_permission` — qolganlari uchun.
    """

    read_actions = ("list", "retrieve")
    read_permission = IsSuperAdmin | IsTeacher
    write_permission = IsSuperAdmin

    def get_course(self):
        if not hasattr(self, "_course"):
            self._course = get_object_or_404(
                selectors.courses_visible_to(self.request.user), pk=self.kwargs["course_pk"]
            )
        return self._course

    def get_permissions(self):
        permission = (
            self.read_permission if self.action in self.read_actions else self.write_permission
        )
        return [permission()]


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


# --------------------------------------------------------------------------
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

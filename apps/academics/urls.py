from rest_framework_nested import routers

from .views import (
    CourseTeacherViewSet,
    CourseViewSet,
    EnrollmentViewSet,
    GroupStudentViewSet,
    GroupViewSet,
    ModuleViewSet,
)

router = routers.DefaultRouter(trailing_slash=False)
router.register("courses", CourseViewSet, basename="course")

courses_router = routers.NestedSimpleRouter(router, "courses", lookup="course")
courses_router.register("teachers", CourseTeacherViewSet, basename="course-teacher")
courses_router.register("students", EnrollmentViewSet, basename="course-student")
courses_router.register("modules", ModuleViewSet, basename="course-module")
courses_router.register("groups", GroupViewSet, basename="course-group")

groups_router = routers.NestedSimpleRouter(courses_router, "groups", lookup="group")
groups_router.register("students", GroupStudentViewSet, basename="course-group-student")

"""Academics view'lari. Import yo'llari (`apps.academics.views.X`) o'zgarmaydi."""

from .courses import (
    CourseTeacherViewSet,
    CourseViewSet,
    EnrollmentAliasViewSet,
    EnrollmentViewSet,
    StudentMyCoursesView,
)
from .groups import GroupDirectoryViewSet, GroupStudentViewSet, GroupViewSet
from .modules import ModuleViewSet

__all__ = [
    "CourseTeacherViewSet",
    "CourseViewSet",
    "EnrollmentAliasViewSet",
    "EnrollmentViewSet",
    "GroupDirectoryViewSet",
    "GroupStudentViewSet",
    "GroupViewSet",
    "ModuleViewSet",
    "StudentMyCoursesView",
]

"""Academics view'lari uchun umumiy: COURSE_PK parametri va nested mixin."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
)
from rest_framework.generics import get_object_or_404

from common.permissions import IsSuperAdmin, IsTeacher

from .. import selectors

COURSE_PK = OpenApiParameter(
    "course_pk", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Kurs ID si"
)


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

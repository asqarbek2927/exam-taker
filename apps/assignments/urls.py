from rest_framework.routers import DefaultRouter

from .views import AssignmentViewSet

router = DefaultRouter(trailing_slash=False)
router.register("exam-assignments", AssignmentViewSet, basename="exam-assignment")

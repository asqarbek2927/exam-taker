from rest_framework.routers import DefaultRouter

from .views import ExamViewSet

router = DefaultRouter(trailing_slash=False)
router.register("exams", ExamViewSet, basename="exam")

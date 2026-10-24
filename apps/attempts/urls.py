from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AnswerGradeView, AttemptViewSet, PendingGradingView

router = DefaultRouter(trailing_slash=False)
router.register("attempts", AttemptViewSet, basename="attempt")

grading_urlpatterns = [
    path("grading/pending", PendingGradingView.as_view(), name="grading-pending"),
    path("answers/<uuid:answer_id>/grade", AnswerGradeView.as_view(), name="answer-grade"),
]

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    StudentViewSet,
    TeacherViewSet,
    UserViewSet,
)

router = DefaultRouter(trailing_slash=False)
router.register("users", UserViewSet, basename="user")
router.register("teachers", TeacherViewSet, basename="teacher")
router.register("students", StudentViewSet, basename="student")

auth_urlpatterns = [
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/refresh", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", MeView.as_view(), name="auth-me"),
]

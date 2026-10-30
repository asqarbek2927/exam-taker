from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminAccountViewSet,
    ChangeOwnPasswordView,
    LoginView,
    LogoutView,
    MeView,
    ProfilePhotoView,
    ProfileView,
    RefreshView,
    StudentViewSet,
    TeacherViewSet,
)

router = DefaultRouter(trailing_slash=False)
router.register("admin/accounts", AdminAccountViewSet, basename="admin-account")
router.register("teachers", TeacherViewSet, basename="teacher")
router.register("students", StudentViewSet, basename="student")

auth_urlpatterns = [
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/refresh", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", MeView.as_view(), name="auth-me"),
    path("profile", ProfileView.as_view(), name="profile"),
    path("profile/photo", ProfilePhotoView.as_view(), name="profile-photo"),
    path(
        "profile/change-password",
        ChangeOwnPasswordView.as_view(),
        name="profile-change-password",
    ),
]

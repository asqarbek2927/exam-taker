from django.urls import path

from .views import (
    AdminDashboardView,
    ResultListView,
    ResultSummaryView,
    StudentDashboardView,
    TeacherDashboardView,
)

urlpatterns = [
    path("results", ResultListView.as_view(), name="results"),
    path("results/summary", ResultSummaryView.as_view(), name="results-summary"),
    path("admin/dashboard", AdminDashboardView.as_view(), name="dashboard-admin"),
    path("teacher/dashboard", TeacherDashboardView.as_view(), name="dashboard-teacher"),
    path("student/dashboard", StudentDashboardView.as_view(), name="dashboard-student"),
]

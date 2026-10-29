from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.academics.urls import courses_router, groups_router
from apps.academics.urls import router as academics_router
from apps.assignments.urls import router as assignments_router
from apps.attempts.urls import grading_urlpatterns
from apps.attempts.urls import router as attempts_router
from apps.exams.urls import router as exams_router
from apps.notifications.urls import router as notifications_router
from apps.questions.urls import router as questions_router
from apps.reports.urls import urlpatterns as reports_urlpatterns
from apps.users.urls import auth_urlpatterns
from apps.users.urls import router as users_router

# Bitta root router: users + academics resurslari (`/api/v1/...`).
api_router = DefaultRouter(trailing_slash=False)
api_router.registry.extend(users_router.registry)
api_router.registry.extend(academics_router.registry)
api_router.registry.extend(questions_router.registry)
api_router.registry.extend(exams_router.registry)
api_router.registry.extend(assignments_router.registry)
api_router.registry.extend(attempts_router.registry)
api_router.registry.extend(notifications_router.registry)

api_v1_patterns = [
    *auth_urlpatterns,
    *grading_urlpatterns,
    *reports_urlpatterns,
    path("", include(api_router.urls)),
    path("", include(courses_router.urls)),
    path("", include(groups_router.urls)),
]

handler404 = "common.views.not_found"
handler500 = "common.views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1_patterns)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.ENABLE_API_DOCS:
    urlpatterns += [
        path("api/schema", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]

"""O‘qish querylari — academics."""

from django.db.models import Count, IntegerField, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from apps.users.choices import UserRole

from .choices import CourseStatus, EnrollmentStatus, GroupStatus, ModuleStatus
from .models import Course, CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup


def _count_for(model, outer_field: str, *conditions, **filters):
    """`model` qatorlari sonini correlated subquery sifatida qaytaradi.

    JOIN + `Count(distinct=True)` o‘rniga subquery ishlatiladi: bir nechta sanoq
    bitta querydagi joinlar ko‘paytmasidan (cartesian explosion) saqlanadi.
    """
    subquery = (
        model.objects.filter(*conditions, **{outer_field: OuterRef("pk")}, **filters)
        .order_by()
        .values(outer_field)
        .annotate(n=Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(subquery, output_field=IntegerField()), 0)


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
def has_course_access(user, course: Course) -> bool:
    """Super Admin yoki kursga biriktirilgan teacher (MAIN/SUPPORT) kurs kontentini boshqaradi."""
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if user.role == UserRole.TEACHER:
        return CourseTeacher.objects.filter(course=course, teacher=user).exists()
    return False


def courses_visible_to(user) -> QuerySet[Course]:
    """Foydalanuvchi ko‘ra oladigan kurslar (queryset scoping — 1-qatlam himoya)."""
    qs = Course.objects.all()
    if user.role == UserRole.SUPER_ADMIN:
        return qs
    # Subquery (join emas): keyingi annotatsiyalar natijasi buzilmasligi uchun.
    if user.role == UserRole.TEACHER:
        return qs.filter(pk__in=CourseTeacher.objects.filter(teacher=user).values("course_id"))
    if user.role == UserRole.STUDENT:
        return qs.filter(
            pk__in=Enrollment.objects.filter(
                student=user,
                status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.COMPLETED],
            ).values("course_id")
        )
    return qs.none()


def with_course_stats(qs: QuerySet[Course]) -> QuerySet[Course]:
    # Lazy import: questions/exams applari academics ga bog‘liq (aylanma import bo‘lmasligi uchun).
    from apps.exams.choices import ExamStatus
    from apps.exams.models import Exam
    from apps.questions.choices import QuestionStatus
    from apps.questions.models import Question

    return qs.annotate(
        teachers_count=_count_for(CourseTeacher, "course"),
        students_count=_count_for(Enrollment, "course", status=EnrollmentStatus.ACTIVE),
        groups_count=_count_for(StudyGroup, "course"),
        modules_count=_count_for(Module, "course", status=ModuleStatus.ACTIVE),
        questions_count=_count_for(Question, "course", status=QuestionStatus.ACTIVE),
        exams_count=_count_for(Exam, "course", ~Q(status=ExamStatus.ARCHIVED)),
    ).prefetch_related(
        Prefetch(
            "course_teachers",
            queryset=CourseTeacher.objects.select_related("teacher").order_by(
                "type", "assigned_at"
            ),
        )
    )


def course_list(user) -> QuerySet[Course]:
    return with_course_stats(courses_visible_to(user)).order_by("name", "created_at")


def course_detail_queryset() -> QuerySet[Course]:
    return with_course_stats(Course.objects.all())


def course_catalog_summary() -> dict:
    counts = Course.objects.aggregate(
        total_courses=Count("pk"),
        active_courses=Count("pk", filter=Q(status=CourseStatus.ACTIVE)),
        draft_courses=Count("pk", filter=Q(status=CourseStatus.DRAFT)),
        archived_courses=Count("pk", filter=Q(status=CourseStatus.ARCHIVED)),
    )
    visible_course_statuses = [CourseStatus.DRAFT, CourseStatus.ACTIVE]
    return {
        **counts,
        "learning_modules": Module.objects.filter(
            status=ModuleStatus.ACTIVE,
            course__status__in=visible_course_statuses,
        ).count(),
        "course_enrollments": Enrollment.objects.filter(
            status=EnrollmentStatus.ACTIVE,
            course__status__in=visible_course_statuses,
        ).count(),
    }


def course_teachers(course: Course) -> QuerySet[CourseTeacher]:
    return CourseTeacher.objects.filter(course=course).select_related("teacher")


def course_enrollments(course: Course) -> QuerySet[Enrollment]:
    return Enrollment.objects.filter(course=course).select_related("student")


# --------------------------------------------------------------------------
# Module
# --------------------------------------------------------------------------
PREVIEW_QUESTIONS_LIMIT = 5


def course_modules(course: Course, *, with_question_preview: bool = False) -> QuerySet[Module]:
    from apps.questions.choices import QuestionStatus
    from apps.questions.models import Question

    qs = Module.objects.filter(course=course).annotate(
        question_count=_count_for(Question, "module", status=QuestionStatus.ACTIVE)
    )
    if with_question_preview:
        qs = qs.prefetch_related(
            Prefetch(
                "questions",
                queryset=Question.objects.filter(status=QuestionStatus.ACTIVE).order_by(
                    "created_at"
                )[:PREVIEW_QUESTIONS_LIMIT],
                to_attr="preview_questions",
            )
        )
    return qs


# --------------------------------------------------------------------------
# StudyGroup
# --------------------------------------------------------------------------
def course_groups(course: Course) -> QuerySet[StudyGroup]:
    return (
        StudyGroup.objects.filter(course=course)
        .select_related("course", "main_teacher", "support_teacher")
        .annotate(students_count=Count("group_students"))
        .prefetch_related(
            Prefetch(
                "group_students",
                queryset=GroupStudent.objects.select_related("student").order_by("added_at"),
                to_attr="student_memberships",
            )
        )
    )


def group_directory() -> QuerySet[StudyGroup]:
    return (
        StudyGroup.objects.select_related("course", "main_teacher", "support_teacher")
        .annotate(students_count=Count("group_students"))
        .prefetch_related(
            Prefetch(
                "group_students",
                queryset=GroupStudent.objects.select_related("student").order_by("added_at"),
                to_attr="student_memberships",
            )
        )
    )


def group_directory_summary() -> dict:
    available = Q(course__status__in=[CourseStatus.DRAFT, CourseStatus.ACTIVE])
    counts = StudyGroup.objects.aggregate(
        active_groups=Count("pk", filter=available & Q(status=GroupStatus.ACTIVE)),
        archived_groups=Count("pk", filter=Q(status=GroupStatus.ARCHIVED)),
        teaching_pairs=Count(
            "pk",
            filter=(
                available
                & Q(status=GroupStatus.ACTIVE)
                & Q(main_teacher__isnull=False)
                & Q(support_teacher__isnull=False)
            ),
        ),
    )
    grouped_students = (
        GroupStudent.objects.filter(
            group__status=GroupStatus.ACTIVE,
            group__course__status__in=[CourseStatus.DRAFT, CourseStatus.ACTIVE],
        )
        .values("student_id")
        .distinct()
        .count()
    )
    return {**counts, "grouped_students": grouped_students}


def group_students(group: StudyGroup) -> QuerySet[GroupStudent]:
    return GroupStudent.objects.filter(group=group).select_related("student")

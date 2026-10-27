"""O‘qish querylari — exams."""

from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce

from apps.academics.models import CourseTeacher
from apps.assignments.choices import AssignmentStatus
from apps.assignments.models import ExamAssignment
from apps.users.choices import UserRole

from .choices import ExamStatus
from .models import Exam, ExamModule, ExamQuestion


def _count_for_exam(model, exam_field: str):
    subquery = (
        model.objects.filter(**{exam_field: OuterRef("pk")})
        .order_by()
        .values(exam_field)
        .annotate(n=Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(subquery, output_field=IntegerField()), 0)


def exams_visible_to(user) -> QuerySet[Exam]:
    """Super Admin — hammasi; Teacher — biriktirilgan kurslar imtihonlari; Student — yo‘q."""
    qs = Exam.objects.all()
    if user.role == UserRole.SUPER_ADMIN:
        return qs
    if user.role == UserRole.TEACHER:
        return qs.filter(
            course_id__in=CourseTeacher.objects.filter(teacher=user).values("course_id")
        )
    return qs.none()


def with_totals(qs: QuerySet[Exam]) -> QuerySet[Exam]:
    # Bitta join (exam_questions) — Count va Sum bir-birini ko‘paytirmaydi.
    return qs.annotate(
        questions_count=Count("exam_questions"),
        modules_count=_count_for_exam(ExamModule, "exam"),
        uses_count=_count_for_exam(ExamAssignment, "exam"),
        total_points=Coalesce(
            Sum("exam_questions__points"),
            Decimal("0"),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        ),
    )


def exam_list(user) -> QuerySet[Exam]:
    return with_totals(exams_visible_to(user)).select_related("course", "created_by")


def exam_library_summary(user) -> dict:
    return exams_visible_to(user).aggregate(
        total_exams=Count("pk"),
        draft_exams=Count("pk", filter=Q(status=ExamStatus.DRAFT)),
        ready_exams=Count("pk", filter=Q(status=ExamStatus.READY)),
        archived_exams=Count("pk", filter=Q(status=ExamStatus.ARCHIVED)),
    )


def exam_detail(qs: QuerySet[Exam]) -> QuerySet[Exam]:
    return (
        with_totals(qs)
        .select_related("course", "created_by")
        .prefetch_related(
            Prefetch(
                "exam_modules",
                queryset=ExamModule.objects.select_related("module").order_by(
                    "module__position", "module__created_at"
                ),
            ),
            Prefetch(
                "exam_questions",
                queryset=ExamQuestion.objects.select_related(
                    "question__course", "question__module", "question__created_by"
                )
                .prefetch_related("question__options")
                .order_by("position"),
            ),
        )
    )


# --------------------------------------------------------------------------
# Edit-lock (TZ 9.5 / 15): e’lon qilingan imtihon kontenti o‘zgarmasligi kerak
# --------------------------------------------------------------------------
def exam_has_assignments(exam: Exam) -> bool:
    """Imtihon biror `ExamAssignment` (istalgan holatda, DRAFT ham) bilan bog‘langanmi?

    Hard delete qilish mumkinmi yoki arxivlash kerakmi — shuni hal qiladi (FK `PROTECT`).
    """
    return exam.assignments.exists()


def _locking_assignments() -> QuerySet[ExamAssignment]:
    """Kontentni bloklaydigan e’lonlar: DRAFT emas yoki attempt bo‘lgan."""
    return ExamAssignment.objects.filter(
        ~Q(status=AssignmentStatus.DRAFT) | Q(attempts__isnull=False)
    )


def exam_is_locked(exam: Exam) -> bool:
    """Kontent bloklanadimi? E’lon qilingan (DRAFT emas) assignment yoki attempt bor bo‘lsa — ha.

    DRAFT holatdagi, hech qachon e’lon qilinmagan assignment kontentni bloklamaydi.
    """
    return _locking_assignments().filter(exam=exam).exists()


def question_is_locked(question) -> bool:
    """Savol bloklangan imtihonlarning birida ishlatilgan bo‘lsa — o‘zgartirib bo‘lmaydi."""
    exam_ids = ExamQuestion.objects.filter(question=question).values("exam_id")
    return _locking_assignments().filter(exam_id__in=exam_ids).exists()

"""Demo ma’lumotlar: API ni qo‘lda sinab ko‘rish uchun (Swagger/Postman).

Hammasi haqiqiy service lar orqali yaratiladi (validatsiya, holatlar, baholash — bari ishlaydi),
shuning uchun demo ma’lumot ham real ma’lumot kabi izchil bo‘ladi.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academics import services as academics
from apps.assignments import services as assignments
from apps.assignments.choices import AudienceType
from apps.attempts import services as attempts
from apps.exams import services as exams
from apps.exams.choices import ExamStatus
from apps.questions import services as questions
from apps.questions.choices import QuestionType
from apps.users.models import User

DEFAULT_PASSWORD = "Demo-Pass-123!"
ADMIN_EMAIL = "admin@examtaker.local"
TEACHERS = [
    ("teacher1@examtaker.local", "Aziz Karimov"),
    ("teacher2@examtaker.local", "Malika Yusupova"),
]
STUDENTS = [
    ("student1@examtaker.local", "Sardor Aliyev"),
    ("student2@examtaker.local", "Dilnoza Rahimova"),
    ("student3@examtaker.local", "Jasur Tursunov"),
    ("student4@examtaker.local", "Nilufar Ergasheva"),
    ("student5@examtaker.local", "Bekzod Omonov"),
    ("student6@examtaker.local", "Madina Saidova"),
]

# (kalit, tur, matn, optionlar [(matn, to‘g‘ri)])
BASICS = [
    (
        "list",
        QuestionType.SINGLE_CHOICE,
        "Python da `list` qanday tur?",
        [("O‘zgaruvchan ketma-ketlik", True), ("O‘zgarmas ketma-ketlik", False), ("Lug‘at", False)],
    ),
    (
        "tuple",
        QuestionType.SINGLE_CHOICE,
        "Quyidagilardan qaysi biri o‘zgarmas (immutable) tur?",
        [("list", False), ("dict", False), ("tuple", True)],
    ),
    (
        "mutable",
        QuestionType.MULTIPLE_CHOICE,
        "Qaysi turlar o‘zgaruvchan (mutable)?",
        [("list", True), ("dict", True), ("set", True), ("tuple", False), ("str", False)],
    ),
    (
        "dynamic",
        QuestionType.TRUE_FALSE,
        "Python — dinamik tipli til.",
        [("True", True), ("False", False)],
    ),
    (
        "index",
        QuestionType.TRUE_FALSE,
        "Python da ro‘yxat indekslari 1 dan boshlanadi.",
        [("True", False), ("False", True)],
    ),
    ("gil", QuestionType.OPEN_ENDED, "GIL nima? Qisqacha tushuntiring.", []),
]
FUNCTIONS = [
    (
        "def",
        QuestionType.SINGLE_CHOICE,
        "Funksiya e’lon qilish uchun qaysi kalit so‘z ishlatiladi?",
        [("def", True), ("func", False), ("function", False)],
    ),
    ("lambda", QuestionType.OPEN_ENDED, "`lambda` funksiyani misol bilan tushuntiring.", []),
]


class Command(BaseCommand):
    help = "Demo foydalanuvchilar, kurs, savollar, imtihon, e’lonlar va attemptlar yaratadi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="DEBUG=False muhitda ham ishga tushirishga ruxsat (ehtiyot bo‘ling).",
        )
        parser.add_argument(
            "--password", default=DEFAULT_PASSWORD, help="Barcha demo userlar paroli."
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_production"]:
            raise CommandError(
                "Demo ma’lumotlar faqat DEBUG muhitda yaratiladi. "
                "Ataylab kerak bo‘lsa `--allow-production` bering."
            )
        if User.objects.filter(email=ADMIN_EMAIL).exists():
            self.stdout.write(
                self.style.WARNING("Demo ma’lumotlar allaqachon mavjud — o‘tkazib yuborildi.")
            )
            return

        with transaction.atomic():
            world = self._build(options["password"])
        self._report(world, options["password"])

    # ------------------------------------------------------------------
    def _build(self, password: str) -> dict:
        now = timezone.now()
        admin = User.objects.create_superuser(
            email=ADMIN_EMAIL, password=password, full_name="Demo Admin"
        )
        t1, t2 = (
            User.objects.create_user(email=e, password=password, full_name=n, role="TEACHER")
            for e, n in TEACHERS
        )
        s1, s2, s3, s4, s5, s6 = (
            User.objects.create_user(email=e, password=password, full_name=n, role="STUDENT")
            for e, n in STUDENTS
        )

        python = academics.create_course(name="Python Foundation", description="Python asoslari")
        django = academics.create_course(name="Django Backend", description="Django va DRF")
        academics.assign_teacher(course=python, teacher=t1, teacher_type="MAIN")
        academics.assign_teacher(course=python, teacher=t2, teacher_type="SUPPORT")
        academics.assign_teacher(course=django, teacher=t1, teacher_type="MAIN")
        for student in (s1, s2, s3, s4, s5):
            academics.enroll_student(course=python, student=student)
        for student in (s1, s6):
            academics.enroll_student(course=django, student=student)

        g101 = academics.create_group(course=python, name="G-101")
        g102 = academics.create_group(course=python, name="G-102")
        for student in (s1, s2, s3):
            academics.add_student_to_group(group=g101, student=student)
        for student in (s4, s5):
            academics.add_student_to_group(group=g102, student=student)

        basics_module = academics.create_module(course=python, title="Python asoslari")
        functions_module = academics.create_module(course=python, title="Funksiyalar")

        def make(specs, module):
            return {
                key: questions.create_question(
                    user=t1,
                    course=python,
                    module=module,
                    type=qtype,
                    text=text,
                    options=[{"text": t, "is_correct": c} for t, c in options],
                )
                for key, qtype, text, options in specs
            }

        basics = make(BASICS, basics_module)
        funcs = make(FUNCTIONS, functions_module)

        quiz = exams.create_exam(
            user=t1,
            course=python,
            title="Python asoslari — quiz",
            description="Barcha savol turlari",
            passing_score_percent=Decimal("60"),
            status=ExamStatus.READY,
            modules=[basics_module],
            questions=[{"question": q} for q in basics.values()],
        )
        exams.create_exam(  # DRAFT: READY qilib, e’lon qilib ko‘rish uchun
            user=t1,
            course=python,
            title="Funksiyalar — imtihon (qoralama)",
            passing_score_percent=Decimal("50"),
            modules=[functions_module],
            questions=[{"question": q} for q in funcs.values()],
        )

        active = assignments.create_assignment(
            user=t1,
            exam=quiz,
            audience_type=AudienceType.GROUPS,
            groups=[g101],
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(days=7),
            duration_minutes=30,
            max_attempts=2,
        )
        scheduled = assignments.create_assignment(
            user=t1,
            exam=quiz,
            audience_type=AudienceType.ALL_COURSE_STUDENTS,
            start_at=now + timedelta(days=2),
            end_at=None,
            duration_minutes=20,
            max_attempts=None,
        )
        paused = assignments.create_assignment(
            user=t1,
            exam=quiz,
            audience_type=AudienceType.GROUPS,
            groups=[g102],
            start_at=now - timedelta(hours=1),
            end_at=None,
            duration_minutes=30,
            max_attempts=1,
        )
        assignments.transition(assignment=paused, action="pause")

        # ---- attemptlar (A1): har xil holat: PENDING_GRADING, GRADED(fail), GRADED(pass) ----
        def play(student, picks: dict, essay: str | None = None):
            attempt = attempts.start_attempt(student=student, assignment_id=active.pk)
            eq = {
                key: attempt.assignment.exam.exam_questions.get(question=question)
                for key, question in basics.items()
            }
            for key, texts in picks.items():
                options = basics[key].options.filter(text__in=texts)
                attempts.save_answer(
                    student=student,
                    attempt_id=attempt.pk,
                    exam_question_id=eq[key].pk,
                    option_ids=[o.pk for o in options],
                )
            if essay is not None:
                attempts.save_answer(
                    student=student,
                    attempt_id=attempt.pk,
                    exam_question_id=eq["gil"].pk,
                    text_answer=essay,
                )
            return attempts.submit_attempt(student=student, attempt_id=attempt.pk)

        everything = {
            "list": ["O‘zgaruvchan ketma-ketlik"],
            "tuple": ["tuple"],
            "mutable": ["list", "dict", "set"],
            "dynamic": ["True"],
            "index": ["False"],
        }
        # s1: hammasi to‘g‘ri + esse -> qo‘lda baholashni kutadi
        play(
            s1, everything, essay="GIL — bir vaqtda bitta thread bytecode bajarishini ta’minlaydi."
        )
        # s2: 1-urinish yomon (FAIL), 2-urinish yaxshi (PASS) -> "latest attempt" mantiqi
        play(s2, {"list": ["Lug‘at"], "dynamic": ["False"]})
        play(s2, everything)
        # s3 hech narsa topshirmagan -> `start` ni o‘zingiz sinab ko‘ring

        return {
            "admin": admin,
            "teachers": (t1, t2),
            "students": (s1, s2, s3, s4, s5, s6),
            "course": python,
            "quiz": quiz,
            "active": active,
            "scheduled": scheduled,
            "paused": paused,
        }

    # ------------------------------------------------------------------
    def _report(self, world: dict, password: str) -> None:
        out = self.stdout.write
        out(self.style.SUCCESS("Demo ma’lumotlar yaratildi.\n"))
        out(f"Parol (hammasi uchun): {password}\n")
        out("Rollar:")
        out(f"  Super Admin : {ADMIN_EMAIL}")
        for email, name in TEACHERS:
            out(f"  Teacher     : {email}  ({name})")
        notes = {
            0: "G-101: 1 ta attempt PENDING_GRADING",
            1: "G-101: 2 urinish — oxirgisi PASS",
            2: "G-101: hali topshirmagan -> start qiling",
            3: "G-102: assignment PAUSED",
            4: "G-102: assignment PAUSED",
            5: "faqat Django kursida",
        }
        for index, (email, name) in enumerate(STUDENTS):
            out(f"  Student     : {email}  ({name}) — {notes[index]}")
        out("")
        out(f"Kurs ID        : {world['course'].pk}")
        out(f"Imtihon ID     : {world['quiz'].pk}")
        out(f"ACTIVE e’lon   : {world['active'].pk}  (G-101, 2 urinish)")
        out(f"SCHEDULED e’lon: {world['scheduled'].pk}  (butun kurs, 2 kundan keyin)")
        out(f"PAUSED e’lon   : {world['paused'].pk}  (G-102)")
        out("\nKeyingi qadam: docs/TESTING_UZ.md")

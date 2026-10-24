from types import SimpleNamespace

import pytest

from apps.academics.tests.factories import (
    CourseFactory,
    CourseTeacherFactory,
    EnrollmentFactory,
    ModuleFactory,
)
from apps.assignments.tests.factories import AssignmentFactory
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory, ExamQuestionFactory
from apps.questions.choices import QuestionType
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import StudentFactory, TeacherFactory

# (kalit, tur, ball, optionlar)
SPECS = [
    (
        "single",
        QuestionType.SINGLE_CHOICE,
        2,
        [("Right", True), ("Wrong1", False), ("Wrong2", False)],
    ),
    ("multi", QuestionType.MULTIPLE_CHOICE, 3, [("R1", True), ("R2", True), ("W1", False)]),
    ("tf", QuestionType.TRUE_FALSE, 1, [("True", True), ("False", False)]),
    ("open", QuestionType.OPEN_ENDED, 4, []),
]


def option_id(question, text):
    return str(question.options.get(text=text).id)


@pytest.fixture
def make_world(db):
    """`make_world(open_ended=True, **assignment_kwargs)` — to‘liq tayyor imtihon muhiti."""

    def _make(*, open_ended=True, passing=50, **assignment_kwargs):
        course = CourseFactory()
        teacher = TeacherFactory()
        CourseTeacherFactory(course=course, teacher=teacher)
        student = StudentFactory()
        EnrollmentFactory(course=course, student=student)
        module = ModuleFactory(course=course)
        exam = ExamFactory(
            course=course,
            created_by=teacher,
            status=ExamStatus.READY,
            passing_score_percent=passing,
        )
        questions, exam_questions = {}, {}
        for position, (key, qtype, points, options) in enumerate(SPECS, start=1):
            if key == "open" and not open_ended:
                continue
            question = QuestionFactory(
                course=course, module=module, created_by=teacher, type=qtype, options=options
            )
            questions[key] = question
            exam_questions[key] = ExamQuestionFactory(
                exam=exam, question=question, points=points, position=position
            )
        assignment_kwargs.setdefault("published_by", teacher)
        assignment = AssignmentFactory(exam=exam, ensure_question=False, **assignment_kwargs)
        return SimpleNamespace(
            course=course,
            teacher=teacher,
            student=student,
            exam=exam,
            assignment=assignment,
            q=questions,
            eq=exam_questions,
            total=sum(p for key, _, p, _ in SPECS if key != "open" or open_ended),
        )

    return _make


@pytest.fixture
def world(make_world):
    return make_world()


class Api:
    """Student oqimi uchun qisqa yordamchilar."""

    def __init__(self, client):
        self.client = client

    def start(self, assignment):
        return self.client.post(f"/api/v1/exam-assignments/{assignment.id}/start")

    def answer(self, attempt_id, exam_question, **body):
        eq_id = getattr(exam_question, "id", exam_question)
        return self.client.put(
            f"/api/v1/attempts/{attempt_id}/answers/{eq_id}", body, format="json"
        )

    def submit(self, attempt_id):
        return self.client.post(f"/api/v1/attempts/{attempt_id}/submit")

    def detail(self, attempt_id):
        return self.client.get(f"/api/v1/attempts/{attempt_id}")


@pytest.fixture
def api(auth_client):
    return lambda user: Api(auth_client(user))

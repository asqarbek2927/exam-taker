import factory
from factory.django import DjangoModelFactory

from apps.academics.tests.factories import CourseFactory, ModuleFactory
from apps.exams.choices import ExamStatus
from apps.exams.models import Exam, ExamModule, ExamQuestion
from apps.questions.tests.factories import QuestionFactory
from apps.users.tests.factories import TeacherFactory


class ExamFactory(DjangoModelFactory):
    class Meta:
        model = Exam

    course = factory.SubFactory(CourseFactory)
    created_by = factory.SubFactory(TeacherFactory)
    title = factory.Sequence(lambda n: f"Exam {n}")
    description = ""
    passing_score_percent = 70
    status = ExamStatus.DRAFT


class ExamModuleFactory(DjangoModelFactory):
    class Meta:
        model = ExamModule

    exam = factory.SubFactory(ExamFactory)
    module = factory.SubFactory(ModuleFactory, course=factory.SelfAttribute("..exam.course"))


class ExamQuestionFactory(DjangoModelFactory):
    class Meta:
        model = ExamQuestion

    exam = factory.SubFactory(ExamFactory)
    question = factory.SubFactory(QuestionFactory, course=factory.SelfAttribute("..exam.course"))
    points = 2
    position = factory.Sequence(lambda n: n + 1)

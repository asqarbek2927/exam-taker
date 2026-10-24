import factory
from factory.django import DjangoModelFactory

from apps.academics.tests.factories import CourseFactory, ModuleFactory
from apps.questions.choices import QuestionType
from apps.questions.models import Question, QuestionOption
from apps.users.tests.factories import TeacherFactory

DEFAULT_OPTIONS = {
    QuestionType.SINGLE_CHOICE: [("A", True), ("B", False), ("C", False)],
    QuestionType.MULTIPLE_CHOICE: [("A", True), ("B", True), ("C", False)],
    QuestionType.TRUE_FALSE: [("True", True), ("False", False)],
    QuestionType.OPEN_ENDED: [],
}


class QuestionFactory(DjangoModelFactory):
    class Meta:
        model = Question
        skip_postgeneration_save = True

    course = factory.SubFactory(CourseFactory)
    module = factory.SubFactory(ModuleFactory, course=factory.SelfAttribute("..course"))
    created_by = factory.SubFactory(TeacherFactory)
    type = QuestionType.SINGLE_CHOICE
    text = factory.Sequence(lambda n: f"Question {n}?")
    default_points = 2

    @factory.post_generation
    def options(obj, create, extracted, **kwargs):
        """`options=False` — optionlarsiz; `options=[(text, is_correct), ...]` — maxsus."""
        if not create or extracted is False:
            return
        spec = extracted if extracted is not None else DEFAULT_OPTIONS[obj.type]
        for position, (text, is_correct) in enumerate(spec, start=1):
            QuestionOption.objects.create(
                question=obj, text=text, is_correct=is_correct, position=position
            )

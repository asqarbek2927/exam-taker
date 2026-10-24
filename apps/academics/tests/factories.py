import factory
from factory.django import DjangoModelFactory

from apps.academics.choices import CourseTeacherType
from apps.academics.models import (
    Course,
    CourseTeacher,
    Enrollment,
    GroupStudent,
    Module,
    StudyGroup,
)
from apps.users.tests.factories import StudentFactory, TeacherFactory


class CourseFactory(DjangoModelFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Course {n}")
    description = "Description"


class CourseTeacherFactory(DjangoModelFactory):
    class Meta:
        model = CourseTeacher

    course = factory.SubFactory(CourseFactory)
    teacher = factory.SubFactory(TeacherFactory)
    type = CourseTeacherType.MAIN


class EnrollmentFactory(DjangoModelFactory):
    class Meta:
        model = Enrollment

    course = factory.SubFactory(CourseFactory)
    student = factory.SubFactory(StudentFactory)


class ModuleFactory(DjangoModelFactory):
    class Meta:
        model = Module

    course = factory.SubFactory(CourseFactory)
    title = factory.Sequence(lambda n: f"Module {n}")
    position = factory.Sequence(lambda n: n + 1)


class StudyGroupFactory(DjangoModelFactory):
    class Meta:
        model = StudyGroup

    course = factory.SubFactory(CourseFactory)
    name = factory.Sequence(lambda n: f"Group {n}")


class GroupStudentFactory(DjangoModelFactory):
    class Meta:
        model = GroupStudent

    group = factory.SubFactory(StudyGroupFactory)
    student = factory.SubFactory(StudentFactory)

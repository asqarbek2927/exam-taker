from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.assignments.choices import AssignmentStatus, AudienceType, AvailabilityType
from apps.assignments.models import ExamAssignment, ExamAssignmentGroup, ExamAssignmentStudent
from apps.assignments.snapshots import ensure_assignment_snapshot
from apps.exams.choices import ExamStatus
from apps.exams.tests.factories import ExamFactory, ExamQuestionFactory
from apps.users.tests.factories import TeacherFactory


class AssignmentFactory(DjangoModelFactory):
    """Sukut bo‘yicha: PUBLISHED, hozir ACTIVE, butun kurs auditoriyasi, 2 ta attempt."""

    class Meta:
        model = ExamAssignment
        skip_postgeneration_save = True

    exam = factory.SubFactory(ExamFactory, status=ExamStatus.READY)
    published_by = factory.SubFactory(TeacherFactory)
    audience_type = AudienceType.ALL_COURSE_STUDENTS
    start_at = factory.LazyFunction(lambda: timezone.now() - timedelta(hours=1))
    end_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=1))
    availability_type = factory.LazyAttribute(
        lambda obj: (
            AvailabilityType.OPEN_ENDED if obj.end_at is None else AvailabilityType.TIME_LIMITED
        )
    )
    duration_minutes = 30
    max_attempts = 2
    status = AssignmentStatus.PUBLISHED
    published_at = factory.LazyAttribute(
        lambda obj: None if obj.status == AssignmentStatus.DRAFT else timezone.now()
    )

    @factory.post_generation
    def ensure_question(obj, create, extracted, **kwargs):
        """Imtihonda kamida 1 ta savol bo‘lsin (`ensure_question=False` — o‘tkazib yuborish)."""
        if create and extracted is not False and not obj.exam.exam_questions.exists():
            ExamQuestionFactory(exam=obj.exam)
        if create:
            ensure_assignment_snapshot(obj)


def add_groups(assignment, *groups):
    for group in groups:
        ExamAssignmentGroup.objects.create(assignment=assignment, group=group)


def add_students(assignment, *students):
    for student in students:
        ExamAssignmentStudent.objects.create(assignment=assignment, student=student)

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.assignments.tests.factories import AssignmentFactory
from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt
from apps.users.tests.factories import StudentFactory


class AttemptFactory(DjangoModelFactory):
    """Faol (IN_PROGRESS) attempt; vaqti hali tugamagan."""

    class Meta:
        model = ExamAttempt

    assignment = factory.SubFactory(AssignmentFactory)
    student = factory.SubFactory(StudentFactory)
    attempt_number = 1
    started_at = factory.LazyFunction(lambda: timezone.now() - timedelta(minutes=1))
    deadline_at = factory.LazyFunction(lambda: timezone.now() + timedelta(minutes=29))
    status = AttemptStatus.IN_PROGRESS

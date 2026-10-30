import factory
from factory.django import DjangoModelFactory

from apps.users.choices import UserRole
from apps.users.models import User

DEFAULT_PASSWORD = "Str0ng-Passw0rd!"


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    full_name = factory.Faker("name")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password = DEFAULT_PASSWORD
    role = UserRole.TEACHER

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return model_class.objects.create_user(*args, **kwargs)


class AdminFactory(UserFactory):
    role = UserRole.SUPER_ADMIN
    email = factory.Sequence(lambda n: f"admin{n}@example.com")


class TeacherFactory(UserFactory):
    role = UserRole.TEACHER
    email = factory.Sequence(lambda n: f"teacher{n}@example.com")


class SupportTeacherFactory(UserFactory):
    role = UserRole.SUPPORT_TEACHER
    email = factory.Sequence(lambda n: f"support{n}@example.com")


class StudentFactory(UserFactory):
    role = UserRole.STUDENT
    email = factory.Sequence(lambda n: f"student{n}@example.com")

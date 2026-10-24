import pytest

from apps.academics.tests.factories import CourseTeacherFactory
from apps.attempts.tests.factories import AttemptFactory
from apps.users.tests.factories import StudentFactory, TeacherFactory

pytestmark = pytest.mark.django_db

ATTEMPTS = "/api/v1/attempts"


def test_each_role_sees_only_its_scope(auth_client, admin, world, make_world):
    mine = AttemptFactory(assignment=world.assignment, student=world.student, status="GRADED")
    classmate = StudentFactory()
    theirs = AttemptFactory(assignment=world.assignment, student=classmate)
    other_world = make_world()
    foreign = AttemptFactory(assignment=other_world.assignment, student=other_world.student)

    def ids(user):
        return {a["id"] for a in auth_client(user).get(ATTEMPTS).json()["data"]}

    assert ids(world.student) == {str(mine.id)}
    assert ids(world.teacher) == {str(mine.id), str(theirs.id)}
    assert ids(admin) == {str(mine.id), str(theirs.id), str(foreign.id)}


def test_detail_visibility(auth_client, world, make_world):
    attempt = AttemptFactory(assignment=world.assignment, student=world.student)
    other_world = make_world()

    assert auth_client(world.student).get(f"{ATTEMPTS}/{attempt.id}").status_code == 200
    assert auth_client(world.teacher).get(f"{ATTEMPTS}/{attempt.id}").status_code == 200
    assert auth_client(StudentFactory()).get(f"{ATTEMPTS}/{attempt.id}").status_code == 404
    assert auth_client(other_world.teacher).get(f"{ATTEMPTS}/{attempt.id}").status_code == 404
    assert auth_client(world.teacher).get(f"{ATTEMPTS}/not-a-uuid").status_code == 404


def test_removed_teacher_loses_access(auth_client, world):
    attempt = AttemptFactory(assignment=world.assignment, student=world.student)
    other_course_teacher = TeacherFactory()
    CourseTeacherFactory(teacher=other_course_teacher)  # boshqa kursga biriktirilgan
    assert auth_client(other_course_teacher).get(f"{ATTEMPTS}/{attempt.id}").status_code == 404


def test_filters(auth_client, admin, world):
    graded = AttemptFactory(
        assignment=world.assignment, student=world.student, attempt_number=1, status="GRADED"
    )
    active = AttemptFactory(assignment=world.assignment, student=world.student, attempt_number=2)
    client = auth_client(admin)

    def ids(**params):
        return {a["id"] for a in client.get(ATTEMPTS, params).json()["data"]}

    assert ids(status="GRADED") == {str(graded.id)}
    assert ids(status="IN_PROGRESS") == {str(active.id)}
    assert ids(assignment_id=world.assignment.id) == {str(graded.id), str(active.id)}
    assert ids(exam_id=world.exam.id) == {str(graded.id), str(active.id)}
    assert ids(course_id=world.course.id) == {str(graded.id), str(active.id)}
    assert ids(student_id=world.student.id) == {str(graded.id), str(active.id)}
    assert ids(student_id=StudentFactory().id) == set()
    assert client.get(ATTEMPTS, {"status": "NOPE"}).status_code == 422


def test_list_row_shape_for_staff(auth_client, world):
    AttemptFactory(assignment=world.assignment, student=world.student)
    row = auth_client(world.teacher).get(ATTEMPTS).json()["data"][0]
    assert row["student"]["id"] == str(world.student.id)
    assert row["course"]["id"] == str(world.course.id)
    assert row["exam_title"] == world.exam.title
    assert {"deadline_at", "score", "percentage", "passed"} <= set(row)


def test_list_query_count_is_constant(auth_client, admin, world, django_assert_max_num_queries):
    for number in range(1, 8):
        AttemptFactory(
            assignment=world.assignment,
            student=StudentFactory(),
            attempt_number=number,
            status="GRADED",
        )
    with django_assert_max_num_queries(6):
        assert auth_client(admin).get(ATTEMPTS).status_code == 200


def test_attempts_endpoints_are_read_only_for_list_and_detail(auth_client, world):
    attempt = AttemptFactory(assignment=world.assignment, student=world.student)
    client = auth_client(world.student)
    assert client.post(ATTEMPTS, {}, format="json").status_code == 405
    assert client.patch(f"{ATTEMPTS}/{attempt.id}", {}, format="json").status_code == 405
    assert client.delete(f"{ATTEMPTS}/{attempt.id}").status_code == 405

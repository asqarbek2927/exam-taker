from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.attempts.choices import AttemptStatus
from apps.attempts.models import ExamAttempt, StudentAnswer, StudentAnswerOption
from apps.attempts.tests.conftest import option_id
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def started(api, world):
    client = api(world.student)
    attempt_id = client.start(world.assignment).json()["id"]
    return client, attempt_id


def test_single_choice_save_overwrite_and_clear(started, world):
    client, attempt_id = started
    eq, question = world.eq["single"], world.q["single"]
    right, wrong = option_id(question, "Right"), option_id(question, "Wrong1")

    saved = client.answer(attempt_id, eq, option_ids=[wrong])
    assert saved.status_code == 200
    assert saved.json()["option_ids"] == [wrong]
    assert saved.json()["exam_question_id"] == str(eq.id)

    assert client.answer(attempt_id, eq, option_ids=[right]).json()["option_ids"] == [right]
    assert StudentAnswerOption.objects.count() == 1  # almashtirildi, to‘planmadi

    cleared = client.answer(attempt_id, eq, option_ids=[])
    assert cleared.json()["option_ids"] == []
    assert StudentAnswer.objects.filter(attempt_id=attempt_id).count() == 1
    assert StudentAnswerOption.objects.count() == 0


def test_multiple_choice_accepts_several_and_deduplicates(started, world):
    client, attempt_id = started
    question = world.q["multi"]
    r1, r2 = option_id(question, "R1"), option_id(question, "R2")
    response = client.answer(attempt_id, world.eq["multi"], option_ids=[r1, r2, r1])
    assert response.status_code == 200
    assert sorted(response.json()["option_ids"]) == sorted([r1, r2])

    client.answer(attempt_id, world.eq["multi"], option_ids=[r2])
    assert StudentAnswerOption.objects.count() == 1


def test_true_false_behaves_like_single(started, world):
    client, attempt_id = started
    question = world.q["tf"]
    both = [option_id(question, "True"), option_id(question, "False")]
    assert client.answer(attempt_id, world.eq["tf"], option_ids=both).status_code == 400
    assert client.answer(attempt_id, world.eq["tf"], option_ids=both[:1]).status_code == 200


def test_open_ended_text_save_and_clear(started, world):
    client, attempt_id = started
    saved = client.answer(attempt_id, world.eq["open"], text_answer="  Closure is...  ")
    assert saved.status_code == 200
    assert saved.json()["text_answer"] == "  Closure is...  "  # bo‘sh joylar saqlanadi
    assert client.answer(attempt_id, world.eq["open"], text_answer="").status_code == 200
    assert StudentAnswer.objects.get().text_answer == ""


def test_saved_answers_are_returned_when_resuming(started, world):
    client, attempt_id = started
    right = option_id(world.q["single"], "Right")
    client.answer(attempt_id, world.eq["single"], option_ids=[right])
    client.answer(attempt_id, world.eq["open"], text_answer="draft")

    detail = client.detail(attempt_id).json()
    answers = {q["id"]: q["answer"] for q in detail["questions"]}
    assert answers[str(world.eq["single"].id)] == {
        "option_ids": [right],
        "text_answer": "",
        "revision": 1,
    }
    assert answers[str(world.eq["open"].id)] == {
        "option_ids": [],
        "text_answer": "draft",
        "revision": 1,
    }
    assert answers[str(world.eq["multi"].id)] is None


@pytest.mark.parametrize(
    ("key", "body"),
    [
        ("single", {"text_answer": "nope"}),  # tanlovli savolga matn
        ("single", {}),  # option_ids majburiy
        ("open", {"option_ids": ["00000000-0000-4000-8000-000000000001"]}),
        ("open", {}),  # text_answer majburiy
    ],
)
def test_payload_must_match_question_type(started, world, key, body):
    client, attempt_id = started
    assert client.answer(attempt_id, world.eq[key], **body).status_code == 400


def test_options_must_belong_to_the_question(started, world):
    client, attempt_id = started
    foreign = option_id(world.q["multi"], "R1")
    response = client.answer(attempt_id, world.eq["single"], option_ids=[foreign])
    assert response.status_code == 400
    two = [option_id(world.q["single"], "Right"), option_id(world.q["single"], "Wrong1")]
    assert client.answer(attempt_id, world.eq["single"], option_ids=two).status_code == 400
    assert StudentAnswerOption.objects.count() == 0


def test_malformed_payloads_return_422(started, world):
    client, attempt_id = started
    assert client.answer(attempt_id, world.eq["single"], option_ids=["nope"]).status_code == 422
    too_long = client.answer(attempt_id, world.eq["open"], text_answer="x" * 20001)
    assert too_long.status_code == 422


def test_revision_is_required_and_prevents_stale_overwrite(started, world):
    client, attempt_id = started
    question = world.q["single"]
    right = option_id(question, "Right")
    wrong = option_id(question, "Wrong1")
    url = f"/api/v1/attempts/{attempt_id}/answers/{world.eq['single'].id}"

    missing = client.client.put(url, {"option_ids": [right]}, format="json")
    assert missing.status_code == 422

    first = client.answer(attempt_id, world.eq["single"], option_ids=[right], revision=3)
    assert first.status_code == 200 and first.json()["revision"] == 3

    retry = client.answer(attempt_id, world.eq["single"], option_ids=[right], revision=3)
    assert retry.status_code == 200 and retry.json()["revision"] == 3

    conflict = client.answer(attempt_id, world.eq["single"], option_ids=[wrong], revision=3)
    assert conflict.status_code == 409
    stale = client.answer(attempt_id, world.eq["single"], option_ids=[wrong], revision=2)
    assert stale.status_code == 409


def test_unknown_or_foreign_exam_question_returns_404(started, world, make_world):
    client, attempt_id = started
    other = make_world()
    assert client.answer(attempt_id, other.eq["single"], option_ids=[]).status_code == 404
    assert client.answer(attempt_id, uuid4(), option_ids=[]).status_code == 404


def test_cannot_answer_someone_elses_attempt(api, started, world):
    _, attempt_id = started
    other = StudentFactory()
    response = api(other).answer(attempt_id, world.eq["single"], option_ids=[])
    assert response.status_code == 404


def test_staff_and_anonymous_cannot_answer(auth_client, api_client, started, world):
    _, attempt_id = started
    url = f"/api/v1/attempts/{attempt_id}/answers/{world.eq['single'].id}"
    assert auth_client(world.teacher).put(url, {"option_ids": []}, format="json").status_code == 403
    assert api_client.put(url, {"option_ids": []}, format="json").status_code == 401


def test_cannot_answer_after_submit(started, world):
    client, attempt_id = started
    client.submit(attempt_id)
    response = client.answer(attempt_id, world.eq["open"], text_answer="late")
    assert response.status_code == 409


def test_answer_after_deadline_closes_attempt_and_keeps_earlier_answers(started, world):
    client, attempt_id = started
    right = option_id(world.q["single"], "Right")
    assert client.answer(attempt_id, world.eq["single"], option_ids=[right]).status_code == 200
    ExamAttempt.objects.filter(pk=attempt_id).update(
        deadline_at=timezone.now() - timedelta(seconds=60)
    )

    late = client.answer(attempt_id, world.eq["tf"], option_ids=[option_id(world.q["tf"], "True")])
    assert late.status_code == 409
    assert "Vaqt tugadi" in late.json()["message"]

    attempt = ExamAttempt.objects.get(pk=attempt_id)  # yopilish rollback bo‘lmagan
    # Open-ended savolga matn yozilmagan -> 0 ball, qo‘lda baholash shart emas.
    assert attempt.status == AttemptStatus.GRADED
    assert attempt.score == 2
    assert (
        not StudentAnswer.objects.filter(
            attempt=attempt,
            attempt_question__snapshot_question__source_exam_question_id=world.eq["tf"].id,
        )
        .exclude(points_awarded=0)
        .exists()
    )
    single = StudentAnswer.objects.get(
        attempt=attempt,
        attempt_question__snapshot_question__source_exam_question_id=world.eq["single"].id,
    )
    assert single.points_awarded == 2  # kechikishdan oldingi javob hisobga olindi


def test_answer_within_grace_period_is_accepted(started, world):
    client, attempt_id = started
    ExamAttempt.objects.filter(pk=attempt_id).update(
        deadline_at=timezone.now() - timedelta(seconds=3)  # grace = 10s
    )
    response = client.answer(attempt_id, world.eq["open"], text_answer="just in time")
    assert response.status_code == 200
    assert ExamAttempt.objects.get(pk=attempt_id).status == AttemptStatus.IN_PROGRESS

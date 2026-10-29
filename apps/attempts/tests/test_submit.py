from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.attempts.choices import AttemptStatus, FinalizationReason
from apps.attempts.models import ExamAttempt, StudentAnswer
from apps.attempts.tests.conftest import option_id
from apps.attempts.tests.test_start import contains_key
from apps.users.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db


def answer_all_correct(client, attempt_id, world, *, with_open=True):
    q = world.q
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(q["single"], "Right")])
    client.answer(
        attempt_id,
        world.eq["multi"],
        option_ids=[option_id(q["multi"], "R1"), option_id(q["multi"], "R2")],
    )
    client.answer(attempt_id, world.eq["tf"], option_ids=[option_id(q["tf"], "True")])
    if with_open:
        client.answer(attempt_id, world.eq["open"], text_answer="Essay")


def start(api, world):
    client = api(world.student)
    return client, client.start(world.assignment).json()["id"]


def test_perfect_objective_attempt_is_graded_and_passed(api, make_world):
    world = make_world(open_ended=False)
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world, with_open=False)

    response = client.submit(attempt_id)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "GRADED"
    assert body["score"] == 6 and body["percentage"] == 100 and body["passed"] is True
    assert body["submitted_at"] is not None
    assert (
        ExamAttempt.objects.get(pk=attempt_id).finalization_reason == FinalizationReason.USER_SUBMIT
    )
    assert set(body) == {
        "id", "assignment_id", "exam_id", "exam_title", "attempt_number", "status",
        "started_at", "submitted_at", "score", "percentage", "passed",
        "review_mode", "answer_review_released", "focus_violations", "finalization_reason",
    }  # fmt: skip


def test_all_wrong_answers_fail(api, make_world):
    world = make_world(open_ended=False, passing=50)
    client, attempt_id = start(api, world)
    q = world.q
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(q["single"], "Wrong1")])
    client.answer(attempt_id, world.eq["multi"], option_ids=[option_id(q["multi"], "W1")])
    client.answer(attempt_id, world.eq["tf"], option_ids=[option_id(q["tf"], "False")])

    body = client.submit(attempt_id).json()
    assert (body["score"], body["percentage"], body["passed"]) == (0, 0, False)


def test_unanswered_questions_get_zero_rows(api, make_world):
    world = make_world(open_ended=False)
    client, attempt_id = start(api, world)
    body = client.submit(attempt_id).json()

    assert body["score"] == 0 and body["passed"] is False
    answers = StudentAnswer.objects.filter(attempt_id=attempt_id)
    assert answers.count() == 3  # har bir savol uchun satr yaratildi
    assert set(answers.values_list("points_awarded", flat=True)) == {Decimal("0.00")}
    assert set(answers.values_list("is_correct", flat=True)) == {False}


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        (["R1", "R2"], Decimal("3.00")),
        (["R1"], Decimal("1.50")),
        (["R1", "W1"], Decimal("0.00")),
        (["W1"], Decimal("0.00")),
        (["R1", "R2", "W1"], Decimal("0.00")),
        ([], Decimal("0.00")),
    ],
)
def test_multiple_choice_partial_credit(api, make_world, selection, expected):
    world = make_world(open_ended=False)
    client, attempt_id = start(api, world)
    ids = [option_id(world.q["multi"], text) for text in selection]
    client.answer(attempt_id, world.eq["multi"], option_ids=ids)
    client.submit(attempt_id)

    answer = StudentAnswer.objects.get(
        attempt_id=attempt_id,
        attempt_question__snapshot_question__source_exam_question_id=world.eq["multi"].id,
    )
    assert answer.points_awarded == expected
    assert answer.is_correct is (selection == ["R1", "R2"])


def test_open_ended_with_text_waits_for_manual_grading(api, world):
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world)
    body = client.submit(attempt_id).json()

    assert body["status"] == "PENDING_GRADING"
    assert (body["score"], body["percentage"], body["passed"]) == (None, None, None)
    open_answer = StudentAnswer.objects.get(
        attempt_id=attempt_id,
        attempt_question__snapshot_question__source_exam_question_id=world.eq["open"].id,
    )
    assert open_answer.points_awarded is None and open_answer.is_correct is None
    objective = StudentAnswer.objects.filter(attempt_id=attempt_id).exclude(pk=open_answer.pk)
    assert all(a.points_awarded is not None for a in objective)  # objective baholangan


def test_blank_open_ended_does_not_need_grading(api, world):
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world, with_open=False)
    client.answer(attempt_id, world.eq["open"], text_answer="   ")  # faqat bo‘sh joy
    body = client.submit(attempt_id).json()
    assert body["status"] == "GRADED"
    assert body["score"] == 6 and body["percentage"] == 60 and body["passed"] is True


@pytest.mark.parametrize(
    ("passing", "expected_passed"), [(60, True), (83.33, True), (83.34, False), (100, False)]
)
def test_passing_threshold_is_inclusive(api, make_world, passing, expected_passed):
    world = make_world(open_ended=False, passing=passing)
    client, attempt_id = start(api, world)
    # single (2) + multi (3) to‘g‘ri, tf noto‘g‘ri -> 5/6 = 83.33
    q = world.q
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(q["single"], "Right")])
    client.answer(
        attempt_id,
        world.eq["multi"],
        option_ids=[option_id(q["multi"], "R1"), option_id(q["multi"], "R2")],
    )
    body = client.submit(attempt_id).json()
    assert body["score"] == 5
    assert body["percentage"] == pytest.approx(83.33)
    assert body["passed"] is expected_passed


def test_exact_boundary_percentage_passes(api, make_world):
    world = make_world(open_ended=False, passing=50)
    client, attempt_id = start(api, world)
    q = world.q
    # multi: 3 ball + tf: 0 + single: 0  -> 3/6 = 50% (aynan chegarada)
    client.answer(
        attempt_id,
        world.eq["multi"],
        option_ids=[option_id(q["multi"], "R1"), option_id(q["multi"], "R2")],
    )
    body = client.submit(attempt_id).json()
    assert body["percentage"] == 50 and body["passed"] is True


def test_submit_twice_returns_409(api, world):
    client, attempt_id = start(api, world)
    assert client.submit(attempt_id).status_code == 200
    assert client.submit(attempt_id).status_code == 409


def test_submit_access_rules(api, auth_client, api_client, world):
    _, attempt_id = start(api, world)
    assert api(StudentFactory()).submit(attempt_id).status_code == 404
    url = f"/api/v1/attempts/{attempt_id}/submit"
    assert auth_client(world.teacher).post(url).status_code == 403
    assert api_client.post(url).status_code == 401
    assert ExamAttempt.objects.get(pk=attempt_id).status == AttemptStatus.IN_PROGRESS


def test_submit_after_deadline_uses_only_saved_answers(api, world):
    client, attempt_id = start(api, world)
    q = world.q
    client.answer(attempt_id, world.eq["single"], option_ids=[option_id(q["single"], "Right")])
    deadline = timezone.now() - timedelta(minutes=2)
    ExamAttempt.objects.filter(pk=attempt_id).update(deadline_at=deadline)

    body = client.submit(attempt_id).json()
    attempt = ExamAttempt.objects.get(pk=attempt_id)
    assert attempt.submitted_at == deadline  # kechikkan paytga emas, deadline ga yoziladi
    assert attempt.finalization_reason == FinalizationReason.TIMEOUT
    assert body["status"] == "GRADED"
    assert body["score"] == 2


def test_submit_within_grace_is_regular_submit(api, world):
    client, attempt_id = start(api, world)
    ExamAttempt.objects.filter(pk=attempt_id).update(
        deadline_at=timezone.now() - timedelta(seconds=3)
    )
    before = timezone.now()
    client.submit(attempt_id)
    attempt = ExamAttempt.objects.get(pk=attempt_id)
    assert attempt.submitted_at >= before
    assert attempt.finalization_reason == FinalizationReason.USER_SUBMIT


def test_student_views_after_submit_do_not_leak_answers(api, world):
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world)
    submitted = client.submit(attempt_id)
    detail = client.detail(attempt_id).json()

    for payload in (submitted.json(), detail):
        assert "questions" not in payload and "answers" not in payload
        assert not contains_key(payload, "is_correct")
    assert detail["status"] == "PENDING_GRADING"


def test_score_only_result_never_exposes_answers(api, make_world):
    world = make_world(open_ended=False, result_review_mode="SCORE_ONLY")
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world, with_open=False)

    submitted = client.submit(attempt_id).json()
    detail = client.detail(attempt_id).json()

    for payload in (submitted, detail):
        assert payload["review_mode"] == "SCORE_ONLY"
        assert payload["answer_review_released"] is False
        assert "answers" not in payload
        assert not contains_key(payload, "is_correct")


def test_after_grading_shows_own_answers_without_answer_key(api, make_world):
    world = make_world(open_ended=False, result_review_mode="AFTER_GRADING")
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world, with_open=False)
    client.submit(attempt_id)

    detail = client.detail(attempt_id).json()

    assert detail["review_mode"] == "AFTER_GRADING"
    assert len(detail["answers"]) == 3
    assert all("points_awarded" in answer for answer in detail["answers"])
    assert not contains_key(detail, "is_correct")


def test_after_grading_hides_answers_while_result_is_pending(api, world):
    world.assignment.result_review_mode = "AFTER_GRADING"
    world.assignment.save(update_fields=["result_review_mode", "updated_at"])
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world)

    submitted = client.submit(attempt_id).json()

    assert submitted["status"] == "PENDING_GRADING"
    assert submitted["score"] is None
    assert "answers" not in submitted


def test_full_review_exposes_correct_options_only_after_release(auth_client, api, make_world):
    world = make_world(open_ended=False, result_review_mode="FULL_REVIEW")
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world, with_open=False)
    client.submit(attempt_id)

    before_release = client.detail(attempt_id).json()
    assert "answers" not in before_release
    assert not contains_key(before_release, "is_correct")

    world.assignment.status = "COMPLETED"
    world.assignment.save(update_fields=["status", "updated_at"])
    released = auth_client(world.teacher).post(
        f"/api/v1/exam-assignments/{world.assignment.id}/release-answer-review",
        {"version": world.assignment.version},
        format="json",
    )
    assert released.status_code == 200, released.json()

    detail = client.detail(attempt_id).json()
    assert detail["answer_review_released"] is True
    assert len(detail["answers"]) == 3
    assert contains_key(detail, "is_correct")
    assert any(
        option["is_correct"]
        for answer in detail["answers"]
        for option in answer["question"]["options"]
    )


def test_staff_detail_shows_answers_and_correctness(auth_client, api, world):
    client, attempt_id = start(api, world)
    answer_all_correct(client, attempt_id, world)
    client.submit(attempt_id)

    body = auth_client(world.teacher).get(f"/api/v1/attempts/{attempt_id}").json()
    assert body["student"]["id"] == str(world.student.id)
    answers = {a["exam_question_id"]: a for a in body["answers"]}
    assert [a["position"] for a in body["answers"]] == [1, 2, 3, 4]
    single = answers[str(world.eq["single"].id)]
    assert single["is_correct"] is True and single["points_awarded"] == 2
    assert single["max_points"] == 2
    assert single["selected_option_ids"] == [option_id(world.q["single"], "Right")]
    assert any(
        o["is_correct"] for o in single["question"]["options"]
    )  # staff to‘g‘ri javobni ko‘radi
    open_answer = answers[str(world.eq["open"].id)]
    assert open_answer["text_answer"] == "Essay" and open_answer["points_awarded"] is None

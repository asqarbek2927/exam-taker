"""Assignment kontentini immutable snapshotga ko'chirish.

Snapshot faqat bir marta yaratiladi. Keyingi question/exam tahrirlari shu
assignment va undan boshlangan attemptlarning tarixiy mazmunini o'zgartirmaydi.
"""

from django.db import transaction

from apps.exams.models import ExamQuestion
from apps.questions.choices import QuestionDifficulty

from .models import (
    AssignmentSnapshot,
    AssignmentSnapshotOption,
    AssignmentSnapshotQuestion,
    ExamAssignment,
)


@transaction.atomic
def ensure_assignment_snapshot(assignment: ExamAssignment) -> AssignmentSnapshot:
    existing = AssignmentSnapshot.objects.filter(assignment=assignment).first()
    if existing is not None:
        return existing

    # Bir assignment uchun parallel snapshot yaratilishini oldini oladi.
    assignment = (
        ExamAssignment.objects.select_for_update(of=("self",))
        .select_related("exam")
        .get(pk=assignment.pk)
    )
    existing = AssignmentSnapshot.objects.filter(assignment=assignment).first()
    if existing is not None:
        return existing

    exam = assignment.exam
    snapshot = AssignmentSnapshot.objects.create(
        assignment=assignment,
        source_exam_id=exam.id,
        source_course_id=exam.course_id,
        title=exam.title,
        description=exam.description,
        passing_score_percent=exam.passing_score_percent,
    )
    exam_questions = (
        ExamQuestion.objects.filter(exam=exam)
        .select_related("question")
        .prefetch_related("question__options")
        .order_by("position", "id")
    )
    for question_position, exam_question in enumerate(exam_questions, start=1):
        question = exam_question.question
        snapshot_question = AssignmentSnapshotQuestion.objects.create(
            snapshot=snapshot,
            source_exam_question_id=exam_question.id,
            source_question_id=question.id,
            source_module_id=question.module_id,
            text=question.text,
            type=question.type,
            difficulty=getattr(question, "difficulty", QuestionDifficulty.MEDIUM),
            points=exam_question.points,
            position=question_position,
        )
        AssignmentSnapshotOption.objects.bulk_create(
            AssignmentSnapshotOption(
                question=snapshot_question,
                source_option_id=option.id,
                text=option.text,
                is_correct=option.is_correct,
                position=option_position,
            )
            for option_position, option in enumerate(question.options.all(), start=1)
        )
    return snapshot

from django.db import migrations


def backfill_snapshots(apps, schema_editor):
    Assignment = apps.get_model("assignments", "ExamAssignment")
    Snapshot = apps.get_model("assignments", "AssignmentSnapshot")
    SnapshotQuestion = apps.get_model("assignments", "AssignmentSnapshotQuestion")
    SnapshotOption = apps.get_model("assignments", "AssignmentSnapshotOption")
    ExamQuestion = apps.get_model("exams", "ExamQuestion")
    Attempt = apps.get_model("attempts", "ExamAttempt")
    AttemptQuestion = apps.get_model("attempts", "AttemptQuestion")
    AttemptOption = apps.get_model("attempts", "AttemptQuestionOption")
    StudentAnswer = apps.get_model("attempts", "StudentAnswer")
    StudentAnswerOption = apps.get_model("attempts", "StudentAnswerOption")

    for assignment in Assignment.objects.select_related("exam").iterator():
        exam = assignment.exam
        snapshot, _ = Snapshot.objects.get_or_create(
            assignment=assignment,
            defaults={
                "source_exam_id": exam.id,
                "source_course_id": exam.course_id,
                "title": exam.title,
                "description": exam.description,
                "passing_score_percent": exam.passing_score_percent,
            },
        )
        source_questions = list(
            ExamQuestion.objects.filter(exam_id=exam.id)
            .select_related("question")
            .order_by("position", "id")
        )
        for position, exam_question in enumerate(source_questions, start=1):
            question = exam_question.question
            snapshot_question, _ = SnapshotQuestion.objects.get_or_create(
                snapshot=snapshot,
                source_exam_question_id=exam_question.id,
                defaults={
                    "source_question_id": question.id,
                    "source_module_id": question.module_id,
                    "text": question.text,
                    "type": question.type,
                    "difficulty": question.difficulty,
                    "points": exam_question.points,
                    "position": position,
                },
            )
            source_options = question.options.order_by("position", "id")
            for option_position, option in enumerate(source_options, start=1):
                SnapshotOption.objects.get_or_create(
                    question=snapshot_question,
                    source_option_id=option.id,
                    defaults={
                        "text": option.text,
                        "is_correct": option.is_correct,
                        "position": option_position,
                    },
                )

    for attempt in Attempt.objects.select_related("assignment").iterator():
        snapshot = Snapshot.objects.get(assignment_id=attempt.assignment_id)
        for position, snapshot_question in enumerate(
            snapshot.questions.order_by("position", "id"), start=1
        ):
            attempt_question, _ = AttemptQuestion.objects.get_or_create(
                attempt=attempt,
                snapshot_question=snapshot_question,
                defaults={"position": position},
            )
            for option_position, snapshot_option in enumerate(
                snapshot_question.options.order_by("position", "id"), start=1
            ):
                AttemptOption.objects.get_or_create(
                    attempt_question=attempt_question,
                    snapshot_option=snapshot_option,
                    defaults={"position": option_position},
                )

        for answer in StudentAnswer.objects.filter(attempt=attempt):
            attempt_question = AttemptQuestion.objects.get(
                attempt=attempt,
                snapshot_question__source_exam_question_id=answer.exam_question_id,
            )
            StudentAnswer.objects.filter(pk=answer.pk).update(attempt_question=attempt_question)
            for selection in StudentAnswerOption.objects.filter(student_answer=answer):
                if selection.option_id is None:
                    continue
                attempt_option = AttemptOption.objects.get(
                    attempt_question=attempt_question,
                    snapshot_option__source_option_id=selection.option_id,
                )
                StudentAnswerOption.objects.filter(pk=selection.pk).update(
                    option=None, attempt_option=attempt_option
                )


class Migration(migrations.Migration):
    dependencies = [
        ("attempts", "0003_attemptquestion_attemptquestionoption_and_more"),
        ("questions", "0002_question_difficulty_question_version_and_more"),
    ]

    operations = [migrations.RunPython(backfill_snapshots, migrations.RunPython.noop)]

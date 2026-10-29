from django.db import migrations


def unlink_snapshot_answers(apps, schema_editor):
    StudentAnswer = apps.get_model("attempts", "StudentAnswer")
    StudentAnswer.objects.filter(attempt_question__isnull=False).update(exam_question=None)


class Migration(migrations.Migration):
    dependencies = [
        ("attempts", "0005_remove_studentanswer_uniq_answer_per_question_and_more"),
    ]

    operations = [migrations.RunPython(unlink_snapshot_answers, migrations.RunPython.noop)]

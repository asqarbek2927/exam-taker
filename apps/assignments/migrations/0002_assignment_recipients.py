import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def snapshot_existing_recipients(apps, schema_editor):
    Assignment = apps.get_model("assignments", "ExamAssignment")
    AssignmentGroup = apps.get_model("assignments", "ExamAssignmentGroup")
    AssignmentStudent = apps.get_model("assignments", "ExamAssignmentStudent")
    Recipient = apps.get_model("assignments", "ExamAssignmentRecipient")
    Enrollment = apps.get_model("academics", "Enrollment")
    GroupStudent = apps.get_model("academics", "GroupStudent")

    Assignment.objects.exclude(status="DRAFT").filter(published_at=None).update(
        published_at=models.F("created_at")
    )

    rows = []
    assignments = Assignment.objects.exclude(status="DRAFT").select_related("exam")
    for assignment in assignments.iterator():
        eligible = Enrollment.objects.filter(
            course_id=assignment.exam.course_id,
            status="ACTIVE",
            student__role="STUDENT",
            student__status="ACTIVE",
        ).values_list("student_id", flat=True)
        if assignment.audience_type == "GROUPS":
            group_ids = AssignmentGroup.objects.filter(assignment=assignment).values("group_id")
            in_groups = GroupStudent.objects.filter(group_id__in=group_ids).values("student_id")
            eligible = eligible.filter(student_id__in=in_groups)
        elif assignment.audience_type == "SPECIFIC_STUDENTS":
            selected = AssignmentStudent.objects.filter(assignment=assignment).values("student_id")
            eligible = eligible.filter(student_id__in=selected)
        rows.extend(
            Recipient(assignment_id=assignment.id, student_id=student_id)
            for student_id in eligible
        )
    Recipient.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("assignments", "0001_initial"),
        ("academics", "0003_unique_main_teacher_per_course"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="examassignment",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ExamAssignmentRecipient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                (
                    "assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recipients",
                        to="assignments.examassignment",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignment_recipients",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "exam_assignment_recipients"},
        ),
        migrations.AddConstraint(
            model_name="examassignmentrecipient",
            constraint=models.UniqueConstraint(
                fields=("assignment", "student"), name="uniq_assignment_recipient"
            ),
        ),
        migrations.RunPython(snapshot_existing_recipients, migrations.RunPython.noop),
    ]

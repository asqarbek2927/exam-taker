from django.conf import settings
from django.db import models

from common.models import TimeStampedModel, UUIDModel

from .choices import CourseStatus, CourseTeacherType, EnrollmentStatus, ModuleStatus


class Course(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=CourseStatus.choices, default=CourseStatus.ACTIVE, db_index=True
    )

    class Meta:
        db_table = "courses"
        ordering = ["name", "created_at"]

    def __str__(self) -> str:
        return self.name


class CourseTeacher(UUIDModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="course_teachers")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="course_assignments"
    )
    type = models.CharField(max_length=10, choices=CourseTeacherType.choices)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "course_teachers"
        ordering = ["type", "assigned_at"]  # MAIN < SUPPORT
        constraints = [
            models.UniqueConstraint(fields=["course", "teacher"], name="uniq_course_teacher"),
        ]

    def __str__(self) -> str:
        return f"{self.teacher_id} @ {self.course_id} ({self.type})"


class Enrollment(UUIDModel):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollments")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrollments"
    )
    status = models.CharField(
        max_length=10,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ACTIVE,
        db_index=True,
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "enrollments"
        ordering = ["-enrolled_at"]
        constraints = [
            models.UniqueConstraint(fields=["course", "student"], name="uniq_course_student"),
        ]

    def __str__(self) -> str:
        return f"{self.student_id} in {self.course_id} ({self.status})"


class StudyGroup(UUIDModel, TimeStampedModel):
    """Kurs ichidagi o‘quv guruhi (Django `auth.Group` bilan adashmaslik uchun nomi shunday)."""

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="groups")
    name = models.CharField(max_length=255)

    class Meta:
        db_table = "study_groups"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["course", "name"], name="uniq_group_name_per_course"),
        ]

    def __str__(self) -> str:
        return self.name


class GroupStudent(UUIDModel):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="group_students")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="group_memberships"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "group_students"
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(fields=["group", "student"], name="uniq_group_student"),
        ]

    def __str__(self) -> str:
        return f"{self.student_id} in {self.group_id}"


class Module(UUIDModel, TimeStampedModel):
    """Kurs ichidagi umumiy (shared) modul — kursning har bir teacheri tahrirlaydi."""

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="modules")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=10, choices=ModuleStatus.choices, default=ModuleStatus.ACTIVE, db_index=True
    )

    class Meta:
        db_table = "modules"
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["course", "status"], name="idx_module_course_status")]

    def __str__(self) -> str:
        return self.title

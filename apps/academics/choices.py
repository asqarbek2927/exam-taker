from django.db import models


class CourseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class CourseTeacherType(models.TextChoices):
    MAIN = "MAIN", "Main"
    SUPPORT = "SUPPORT", "Support"


class EnrollmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    REMOVED = "REMOVED", "Removed"


class ModuleStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class GroupStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"

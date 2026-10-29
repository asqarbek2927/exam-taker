from django.db import models


class AuditAction(models.TextChoices):
    ASSIGNMENT_TRANSITION = "ASSIGNMENT_TRANSITION", "Assignment transition"
    ASSIGNMENT_DELETED = "ASSIGNMENT_DELETED", "Assignment deleted"
    ANSWER_REVIEW_RELEASED = "ANSWER_REVIEW_RELEASED", "Answer review released"
    ANSWER_GRADED = "ANSWER_GRADED", "Answer graded"
    ATTEMPT_INTEGRITY_EVENT = "ATTEMPT_INTEGRITY_EVENT", "Attempt integrity event"

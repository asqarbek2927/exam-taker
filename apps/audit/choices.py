from django.db import models


class AuditAction(models.TextChoices):
    ACCOUNT_CREATED = "ACCOUNT_CREATED", "Account created"
    ACCOUNT_UPDATED = "ACCOUNT_UPDATED", "Account updated"
    ACCOUNT_STATUS_CHANGED = "ACCOUNT_STATUS_CHANGED", "Account status changed"
    ACCOUNT_DELETED = "ACCOUNT_DELETED", "Account deleted"
    TEMP_PASSWORD_ISSUED = "TEMP_PASSWORD_ISSUED", "Temporary password issued"
    TEACHING_COURSES_UPDATED = "TEACHING_COURSES_UPDATED", "Teaching courses updated"
    ASSIGNMENT_TRANSITION = "ASSIGNMENT_TRANSITION", "Assignment transition"
    ASSIGNMENT_DELETED = "ASSIGNMENT_DELETED", "Assignment deleted"
    ANSWER_REVIEW_RELEASED = "ANSWER_REVIEW_RELEASED", "Answer review released"
    ANSWER_GRADED = "ANSWER_GRADED", "Answer graded"
    ATTEMPT_INTEGRITY_EVENT = "ATTEMPT_INTEGRITY_EVENT", "Attempt integrity event"
    ATTEMPTS_DELETED = "ATTEMPTS_DELETED", "Attempt deleted"
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED", "Login succeeded"
    QUESTION_UPDATED = "QUESTION_UPDATED", "Question updated"
    QUESTION_DELETED = "QUESTION_DELETED", "Question deleted or archived"
    QUESTION_RESTORED = "QUESTION_RESTORED", "Question restored"
    QUESTIONS_IMPORTED = "QUESTIONS_IMPORTED", "Questions imported"
    EXAM_UPDATED = "EXAM_UPDATED", "Exam updated"
    EXAM_DELETED = "EXAM_DELETED", "Exam deleted or archived"

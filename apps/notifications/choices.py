from django.db import models


class NotificationType(models.TextChoices):
    ASSIGNMENT = "ASSIGNMENT", "Assignment"
    RESULT = "RESULT", "Result"
    SYSTEM = "SYSTEM", "System"

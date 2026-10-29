import uuid

from django.db import models


class UUIDModel(models.Model):
    """UUID primary key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VersionedModel(models.Model):
    """Optimistic locking uchun API versiyasi.

    Versiyani oshirish service qatlamida, kutilgan versiya bilan atomik update
    bajarilgan paytda amalga oshiriladi. Oddiy ``save()`` uni yashirin ravishda
    o'zgartirmaydi — bu fixtures va admin amallarini predictible saqlaydi.
    """

    version = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        abstract = True

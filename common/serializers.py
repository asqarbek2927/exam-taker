from rest_framework import serializers


class ArchivedResponseSerializer(serializers.Serializer):
    """`DELETE` obyekt arxivlanganda qaytadigan javob (faqat OpenAPI sxemasi uchun)."""

    archived = serializers.BooleanField()

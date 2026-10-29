import uuid

import pytest

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit

pytestmark = pytest.mark.django_db


def test_sensitive_metadata_is_removed_recursively(teacher):
    event = record_audit(
        actor=teacher,
        action=AuditAction.ASSIGNMENT_TRANSITION,
        entity_type="assignment",
        entity_id=uuid.uuid4(),
        metadata={
            "status": "ACTIVE",
            "password": "never-store",
            "access_token": "never-store",
            "nested": {
                "teacher_feedback": "private",
                "correct_option_ids": ["secret-key"],
                "version": 2,
            },
        },
    )

    assert event.metadata == {
        "status": "ACTIVE",
        "nested": {"version": 2},
    }

    event.metadata = {"status": "CANCELLED"}
    with pytest.raises(TypeError):
        event.save()
    with pytest.raises(TypeError):
        event.delete()

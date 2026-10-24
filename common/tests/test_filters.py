import uuid

import pytest
from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from common.filters import parse_uuid_list


def test_parses_repeated_and_comma_separated_values_without_duplicates():
    a, b = uuid.uuid4(), uuid.uuid4()
    query = QueryDict(f"ids={a}&ids={b},{a}&ids=")
    assert parse_uuid_list(query, "ids") == [a, b]


def test_missing_param_returns_empty_list():
    assert parse_uuid_list(QueryDict(""), "ids") == []


def test_invalid_uuid_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_uuid_list(QueryDict("ids=nope"), "ids")

"""OpenAPI sxemasi o‘zgarmaganini tekshiradi (production front himoyasi)."""

import pytest
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.renderers import OpenApiYamlRenderer

from common.tests.snapshot import assert_matches_snapshot

pytestmark = pytest.mark.django_db


def test_openapi_schema_matches_baseline():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    text = OpenApiYamlRenderer().render(schema, renderer_context={}).decode("utf-8")
    assert_matches_snapshot("openapi_baseline.yml", text)

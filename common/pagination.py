from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """`?page=1&limit=20` — TZ dagi pagination kontrakti."""

    page_size = 20
    page_size_query_param = "limit"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "data": data,
                "pagination": {
                    "page": self.page.number,
                    "limit": self.get_page_size(self.request),
                    "total": self.page.paginator.count,
                    "total_pages": self.page.paginator.num_pages,
                },
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "required": ["data", "pagination"],
            "properties": {
                "data": schema,
                "pagination": {
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer", "example": 1},
                        "limit": {"type": "integer", "example": 20},
                        "total": {"type": "integer", "example": 125},
                        "total_pages": {"type": "integer", "example": 7},
                    },
                },
            },
        }

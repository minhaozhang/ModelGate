import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from core.i18n import render
from routes.user import user_api_document_detail


def make_request(path: str = "/user/api/documents/1", cookies=None):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "cookies": cookies or {},
            "root_path": "",
        }
    )


class UserDocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_detail_api_supports_serialized_document_dict(self):
        request = make_request()
        serialized_doc = {
            "id": 1,
            "title": "Guide",
            "category": "General",
            "content": "# Hello",
            "is_published": True,
            "updated_at": "2026-04-13T20:00:00",
        }

        with patch(
            "services.documents.get_document", new=AsyncMock(return_value=serialized_doc)
        ):
            result = await user_api_document_detail(request=request, doc_id=1, api_key_id=123)

        self.assertEqual(result["id"], 1)
        self.assertEqual(result["title"], "Guide")
        self.assertEqual(result["category"], "General")
        self.assertEqual(result["content"], "# Hello")
        self.assertEqual(result["updated_at"], "2026-04-13T20:00:00")

    def test_documents_page_template_does_not_reference_undefined_locale_variable(self):
        html = render(make_request("/user/documents"), "user/documents.html")

        self.assertIn('const current_locale = "en";', html)
        self.assertIn("current_locale ===", html)
        self.assertIn("All Categories", html)

    def test_documents_page_template_has_valid_read_more_span(self):
        html = render(make_request("/user/documents"), "user/documents.html")

        self.assertNotIn("鈫?/span>", html)
        self.assertIn("</span>", html)


if __name__ == "__main__":
    unittest.main()

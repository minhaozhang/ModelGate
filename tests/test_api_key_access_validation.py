import unittest

from app.routes.keys import _validate_access_payload


class ApiKeyAccessValidationTests(unittest.TestCase):
    def test_rejects_empty_access_without_explicit_all_mode(self):
        response = _validate_access_payload(None, [], [], required=True)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)

    def test_all_mode_is_not_a_valid_access_mode(self):
        response = _validate_access_payload("all", [], [], required=True)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)

    def test_model_modes_require_non_empty_selection(self):
        self.assertEqual(
            _validate_access_payload("model", [], [], required=True).status_code,
            400,
        )
        self.assertEqual(
            _validate_access_payload("provider_model", [], [], required=True).status_code,
            400,
        )
        self.assertIsNone(_validate_access_payload("model", [], [101], required=True))
        self.assertIsNone(
            _validate_access_payload("provider_model", [11], [], required=True)
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from app.routes.keys import _validate_access_payload


class ApiKeyAccessValidationTests(unittest.TestCase):
    """An empty allowed_model_ids list is a legitimate state since
    check_model_access denies keys with no bindings: the key can be saved
    with zero models (effectively disabled)."""

    def test_empty_access_without_mode_defaults_to_model(self):
        self.assertIsNone(_validate_access_payload(None, []))

    def test_all_mode_is_not_a_valid_access_mode(self):
        response = _validate_access_payload("all", [])

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)

    def test_provider_model_mode_is_not_a_valid_access_mode(self):
        response = _validate_access_payload("provider_model", [11])

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 400)

    def test_model_mode_accepts_empty_and_non_empty_selection(self):
        self.assertIsNone(_validate_access_payload("model", []))
        self.assertIsNone(_validate_access_payload("model", [101]))


if __name__ == "__main__":
    unittest.main()

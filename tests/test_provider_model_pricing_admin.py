import unittest


class PricingAdminRoutesTests(unittest.TestCase):
    def test_batch_pricing_route_exists(self):
        from app.routes import provider_models
        import inspect
        funcs = [
            name
            for name, _ in inspect.getmembers(provider_models, inspect.iscoroutinefunction)
        ]
        self.assertIn("batch_update_provider_model_pricing", funcs)

    def test_copy_and_sync_routes_exist(self):
        from app.routes import provider_models
        import inspect
        funcs = [
            name
            for name, _ in inspect.getmembers(provider_models, inspect.iscoroutinefunction)
        ]
        self.assertIn("copy_provider_model_pricing", funcs)
        self.assertIn("sync_pricing_to_siblings", funcs)

    def test_export_csv_route_exists(self):
        from app.routes import provider_models
        import inspect
        funcs = [
            name
            for name, _ in inspect.getmembers(provider_models, inspect.iscoroutinefunction)
        ]
        self.assertIn("export_provider_model_pricing_csv", funcs)


if __name__ == "__main__":
    unittest.main()

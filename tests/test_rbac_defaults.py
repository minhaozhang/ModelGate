import unittest

from app.core import database


class RbacDefaultSeedTests(unittest.TestCase):
    def test_default_rbac_permissions_cover_route_permission_codes(self):
        permissions = database.default_rbac_permissions()
        codes = {item["code"] for item in permissions}

        expected = {
            "page.providers",
            "provider.update_key",
            "page.provider_models",
            "provider_model.update",
            "page.roles",
            "page.users",
            "page.logs.requests",
            "page.system.config",
            "page.system.scheduler",
            "page.stats",
        }

        self.assertTrue(expected.issubset(codes))
        self.assertEqual(len(codes), len(permissions))

    def test_default_rbac_roles_include_admin_role(self):
        roles = database.default_rbac_roles()

        self.assertIn("admin", {role["name"] for role in roles})

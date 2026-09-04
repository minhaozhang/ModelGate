"""Integration tests that execute real SQL against the configured database.

These guard against PostgreSQL runtime errors (e.g. GroupingError caused by
bind-parameter re-numbering when the same expression is built twice) that
mocked unit tests cannot catch.
"""

import os
import unittest

from app.core.db_engine import DATABASE_URL


def _database_available() -> bool:
    return bool(DATABASE_URL)


class MonitorDetailsIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(_database_available(), "DATABASE_URL not configured")
    def test_monitor_details_all_periods_execute(self):
        import asyncio

        from app.routes.stats import get_monitor_details

        async def run():
            results = {}
            for period in ["day", "week", "month", "year"]:
                result = await get_monitor_details(period=period)
                results[period] = result
            return results

        results = asyncio.run(run())
        for period, result in results.items():
            with self.subTest(period=period):
                self.assertIn("latency", result)
                latency = result["latency"]
                self.assertIn("providers", latency)
                self.assertIn("provider_series", latency)


if __name__ == "__main__":
    unittest.main()

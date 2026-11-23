"""Regression tests: stale, unchanged, newer and failed Combat Lab responses."""
import json
import time
import unittest
from unittest.mock import patch

from combat_source import fetch_snapshot, is_fresh, save_run_status, status_label, parse_page_snapshot


class FakeResponse:
    status = 200

    def __init__(self, generated_ms):
        self.payload = {"generatedAtMs": generated_ms}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return json.dumps(self.payload).encode("utf-8")


def parser(payload, primary, secondary):
    return {"generatedAtMs": payload["generatedAtMs"], "primary": primary, "secondary": secondary,
            "generatedAtUTC": "sample"}


class SourceFetchTests(unittest.TestCase):
    def check(self, values, previous):
        with patch("combat_source.fetch_page_snapshot", side_effect=ValueError("fixture has no HTML")) as page_mock, patch("combat_source.urlopen", side_effect=[
            FakeResponse(v) if isinstance(v, int) else v for v in values
        ]) as mocked, patch("combat_source.time.sleep"):
            result = fetch_snapshot(595, 621, previous, parser)
        return result, mocked.call_count

    def test_nextjs_page_matches_weighted_trade(self):
        summary = {"battles": 1044316, "uniqueGovernors": 4733,
                   "killPointsGained": 18849988023, "killPointsLost": 13507127397,
                   "weightedTradePercent": 139.55586164965524,
                   "dps": 458.42098323560936, "sps": 76.39694681958183,
                   "tps": 54.1651927972214, "hps": 6.171207375831811}
        data = {"generatedAtMs": 1795393831236,
                "pairing": {"primaryCommanderId": 595, "secondaryCommanderId": 621},
                "ranges": {"7d": {"scenarios": {"openField": {"summary": summary}}}}}
        flight = "a:" + json.dumps(["$", "$L2d", None, {"data": data}])
        html = "<script>self.__next_f.push(" + json.dumps([1, flight]) + ")</script>"
        result = parse_page_snapshot(html, 595, 621)
        self.assertEqual(result["battles"], 1044316)
        self.assertEqual(result["tradePercent"], 139.5559)
        self.assertEqual(result["dps"], 458.421)

    def test_new_generation_skips_retries_when_fresh(self):
        now = int(time.time() * 1000)
        (data, status, error), attempts = self.check([now], now - 60_000)
        self.assertEqual((status, error, attempts), ("new", None, 1))
        self.assertTrue(is_fresh(data))

    def test_unchanged_is_warning_not_error(self):
        now = int(time.time() * 1000)
        (data, status, error), attempts = self.check([now] * 3, now)
        self.assertEqual((status, error, attempts), ("unchanged", None, 3))
        self.assertIn("UNCHANGED", status_label(status, data))

    def test_stale_site_timestamp_is_not_freshened_by_retrieval(self):
        old = int((time.time() - 9 * 3600) * 1000)
        (data, status, error), attempts = self.check([old] * 3, old)
        self.assertEqual((status, error, attempts), ("unchanged", None, 3))
        self.assertFalse(is_fresh(data))
        self.assertIn("STALE", status_label(status, data))

    def test_retry_accepts_new_generation(self):
        now = int(time.time() * 1000)
        previous = now - 60_000
        (data, status, error), attempts = self.check([previous, now], previous)
        self.assertEqual((status, error, attempts), ("new", None, 2))
        self.assertEqual(data["generatedAtMs"], now)

    def test_regression_does_not_overwrite_stored_snapshot(self):
        now = int(time.time() * 1000)
        (data, status, error), attempts = self.check([now - 120_000] * 3, now)
        self.assertIsNone(data)
        self.assertEqual(status, "error")
        self.assertIn("older than stored", error)

    def test_transport_errors_are_explicit(self):
        (data, status, error), attempts = self.check([OSError("offline")] * 3, None)
        self.assertIsNone(data)
        self.assertEqual(status, "error")
        self.assertIn("offline", error)

    def test_success_and_stale_counts_are_separate(self):
        old = int((time.time() - 9 * 3600) * 1000)
        snapshot = {"generatedAtMs": old, "generatedAtUTC": "old"}
        results = {"595-621": {"ok": True, "status": "unchanged",
                                "error": None, "snapshot": snapshot}}
        store = {}
        save_run_status(store, results)
        self.assertEqual(store["lastRunSuccessCount"], 1)
        self.assertEqual(store["lastRunStaleCount"], 1)
        self.assertEqual(store["lastRunUnchangedCount"], 1)
        self.assertEqual(store["lastRunFreshCount"], 0)
        self.assertEqual(store["lastErrors"], {})
        self.assertIn("595-621", store["lastWarnings"])


if __name__ == "__main__":
    unittest.main()

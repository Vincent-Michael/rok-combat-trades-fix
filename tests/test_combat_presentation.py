"""Regression tests for Infantry-style trade reports and SVG ranking charts."""
import time
import unittest

from combat_presentation import build_trade_report, build_trade_svg


class CombatPresentationTests(unittest.TestCase):
    def setUp(self):
        now = int(time.time() * 1000)
        self.pairs = [("Pair B", 20, 21), ("Pair A", 10, 11)]
        self.results = {
            "20-21": {
                "ok": True, "status": "unchanged", "error": None,
                "snapshot": {
                    "generatedAtMs": now, "generatedAtUTC": "2026-11-22 16:29 UTC",
                    "primary": 20, "secondary": 21, "tradePercent": 85.0,
                    "battles": 200, "killPointsGained": 10_000_000,
                    "killPointsLost": 12_000_000, "dps": 1.1, "sps": 2.2, "tps": 3.3,
                },
                "previous": {"tradePercent": 90.0},
            },
            "10-11": {
                "ok": True, "status": "new", "error": None,
                "snapshot": {
                    "generatedAtMs": now, "generatedAtUTC": "2026-11-22 16:29 UTC",
                    "primary": 10, "secondary": 11, "tradePercent": 125.0,
                    "battles": 400, "killPointsGained": 25_000_000,
                    "killPointsLost": 20_000_000, "dps": 3.1, "sps": 4.2, "tps": 5.3,
                },
                "previous": {"tradePercent": 120.0},
            },
        }

    def test_svg_matches_infantry_visual_design(self):
        svg = build_trade_svg("cavalry", self.pairs, self.results)
        self.assertIn('aria-label="Cavalry trade efficiency ranking"', svg)
        self.assertIn("#172234", svg)
        self.assertIn("#22c55e", svg)
        self.assertIn("#ef4444", svg)
        self.assertIn('stroke-dasharray="6 7"', svg)
        self.assertIn(">125.00%</text>", svg)
        self.assertIn(">85.00%</text>", svg)
        self.assertLess(svg.index(">Pair A</text>"), svg.index(">Pair B</text>"))

    def test_report_contains_all_infantry_style_sections_and_units(self):
        report = build_trade_report("cavalry", self.pairs, self.results, "2026-11-22T17:14:18Z")
        for part in (
            "## Trade Efficiency Ranking",
            "![Trade efficiency ranking](charts/cavalry.svg)",
            "## Trade Ranking & Battle Reports",
            "## Detailed Combat Statistics",
            "## Key Findings",
            "https://rokbattles.com/combat-lab?primary=10&secondary=11",
            "25.000M", "20.000M",
            "+5.00", "-5.00",
            "Site-generated snapshot UNCHANGED",
        ):
            self.assertIn(part, report)
        self.assertLess(report.index("Pair A"), report.index("Pair B"))

    def test_archer_uses_own_chart(self):
        report = build_trade_report("archer", self.pairs, self.results, "2026-11-22T17:14:18Z")
        svg = build_trade_svg("archer", self.pairs, self.results)
        self.assertIn("(charts/archer.svg)", report)
        self.assertIn("Archer trade efficiency ranking", svg)

    def test_no_verified_snapshots_have_na_not_fabricated_stats(self):
        results = {"20-21": {"ok": False, "status": "error", "error": "offline",
                            "snapshot": None, "previous": None}}
        report = build_trade_report("archer", self.pairs[:1], results, "2026-11-22T17:14:18Z")
        svg = build_trade_svg("archer", self.pairs[:1], results)
        self.assertIn("UNVERIFIED", report)
        self.assertIn("No verified 7-day/Open Field trade values", report)
        self.assertIn(">N/A</text>", svg)


if __name__ == "__main__":
    unittest.main()

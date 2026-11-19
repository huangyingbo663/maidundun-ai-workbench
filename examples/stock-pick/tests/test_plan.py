import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import plan


class StockPickTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((HERE / "demo.json").read_text(encoding="utf-8"))

    def test_complete_published_output(self):
        expected = (HERE / "expected.txt").read_text(encoding="utf-8")
        self.assertEqual(plan.plan(self.data), expected)
        self.assertIn("账面候选（2 款）", expected)
        self.assertIn("待核（4 款）", expected)
        self.assertIn("本次筛除（3 款）", expected)

    def test_independent_threshold_and_reserved_case(self):
        self.data["threshold"] = 9
        self.data["items"] = [
            {"sku": "ONE", "name": "虚构样品", "store": 6, "cold": 3, "reserved": 1, "in_transit": 0},
            {"sku": "TWO", "name": "另一样品", "store": 9, "cold": 8, "reserved": 0, "in_transit": 0},
        ]
        output = plan.plan(self.data)
        self.assertIn("可调 2，补到筛选线的参考上限 2", output)
        self.assertIn("门店 9，已达到筛选线", output)
        self.assertIn("账面候选（1 款）", output)

    def test_unknown_negative_noninteger_and_inconsistent_amounts(self):
        base = self.data["items"][0]
        for field in plan.QUANTITIES:
            for value in (None, -1, False, 1.5, "7"):
                with self.subTest(field=field, value=value):
                    self.assertEqual(plan.classify({**base, field: value}, 30)[0], "review")
            self.assertEqual(plan.classify({k: v for k, v in base.items() if k != field}, 30)[0], "review")
        self.assertEqual(plan.classify({**base, "reserved": base["cold"] + 1}, 30)[0], "review")

    def test_in_transit_zero_available_and_exact_boundary(self):
        base = self.data["items"][0]
        self.assertEqual(plan.classify({**base, "in_transit": 2}, 30)[0], "review")
        self.assertEqual(plan.classify({**base, "cold": 5, "reserved": 5}, 30)[0], "skip")
        self.assertEqual(plan.classify({**base, "store": 30}, 30)[0], "skip")

    def test_conflicting_sku_not_counted_twice_or_proposed(self):
        base = self.data["items"][0]
        self.data["items"] = [base, {**base, "name": "另一规格", "store": 8}]
        output = plan.plan(self.data)
        self.assertIn("待核（1 款）", output)
        self.assertIn("账面候选（0 款）", output)
        self.assertNotIn("参考上限", output)

    def test_same_instant_different_offsets(self):
        self.data["store_as_of"] = "2025-03-08T00:00:00+00:00"
        self.assertNotIn("时点不同", plan.plan(self.data))

    def test_bad_schema_fails(self):
        for key, value in (("threshold", True), ("threshold", 0), ("items", []),
                           ("store_as_of", "2025-03-08"), ("unit", "")):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                plan.plan({**self.data, key: value})
        with self.assertRaises(ValueError):
            plan.plan({**self.data, "items": [{**self.data["items"][0], "reservd": 99}]})

    def test_cli_preserves_existing_output_and_rejects_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report.txt"
            source = Path(directory) / "input.json"
            options = [sys.executable, "-B", str(HERE / "plan.py"), "--input", str(source), "--output", str(out)]
            source.write_text('{"threshold": 10, "threshold": 20}', encoding="utf-8")
            self.assertNotEqual(subprocess.run(options, capture_output=True).returncode, 0)
            self.assertFalse(out.exists())
            source.write_text(json.dumps(self.data), encoding="utf-8")
            out.write_bytes(b"existing")
            self.assertNotEqual(subprocess.run(options, capture_output=True).returncode, 0)
            self.assertEqual(out.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()

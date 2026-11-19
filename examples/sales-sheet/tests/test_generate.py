import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sales_sheet", ROOT / "generate.py")
sheet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sheet)


class SalesTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "demo.json").read_text(encoding="utf-8"))

    def test_separate(self):
        html = sheet.render(self.data)
        self.assertIn("¥33.45", html)
        self.assertIn("运费另算", html)
        self.assertNotIn("含运费合计", html)
        self.assertEqual(html, (ROOT / "expected.html").read_text(encoding="utf-8"))

    def test_fixed_and_last_row(self):
        self.data["shipping"] = {"mode": "fixed", "amount": "6.50"}
        self.assertIn("¥39.95", sheet.render(self.data))
        self.data["items"][-1]["quantity"] = 5
        self.assertIn("¥42.05", sheet.render(self.data))
        self.data["shipping"]["amount"] = "0.00"
        self.assertIn("¥35.55", sheet.render(self.data))

    def test_escape_and_reject_internal_column(self):
        self.data["items"][0]["name"] = "A < B & C"
        self.assertIn("A &lt; B &amp; C", sheet.render(self.data))
        self.data["items"][0]["internal"] = "private test"
        with self.assertRaises(ValueError):
            sheet.render(self.data)

    def test_invalid_prices_and_quantity(self):
        item = self.data["items"][0]
        for key, value in [("price", "0.001"), ("price", "1e2"), ("price", 12), ("quantity", True), ("quantity", -1)]:
            with self.subTest(value=value):
                data = dict(self.data, items=[dict(item, **{key:value})])
                with self.assertRaises(ValueError):
                    sheet.render(data)

    def test_cli_preserves_existing_output_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "input.json", root / "kept.html"
            cmd = [sys.executable, "-B", str(ROOT/"generate.py"), "--input", str(source), "--output", str(output)]
            source.write_text('{"items":[],"items":[]}', encoding="utf-8")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
            source.write_text(json.dumps(self.data), encoding="utf-8")
            output.write_text("kept", encoding="utf-8")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "kept")

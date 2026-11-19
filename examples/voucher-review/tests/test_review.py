import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("voucher_reconcile", ROOT / "reconcile.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VoucherReviewTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "demo.json").read_text(encoding="utf-8"))

    def test_original(self):
        expected = json.loads((ROOT / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(module.reconcile(self.data), expected)

    def test_later_date(self):
        self.data["end"] = "2026-05-09"
        self.assertEqual(module.reconcile(self.data)["本期支付的券截至期末"]["支付券核销率"], "3/5")

    def test_negative_net_and_empty_denominator(self):
        self.data.update(start="2026-05-04", end="2026-05-04")
        self.data["paid"] = [row for row in self.data["paid"] if row["voucher"] == "B"]
        self.data["events"] = [row for row in self.data["events"] if row["voucher"] == "B"]
        result = module.reconcile(self.data)
        self.assertEqual(result["按事件发生日"]["净核销笔数"], -1)
        self.assertEqual(result["本期支付的券截至期末"]["支付券核销率"], "无可计算分母")

    def test_conflicting_duplicate_and_orphan(self):
        for changed in [{"action": "reverse"}, {"voucher": "unknown"}]:
            with self.subTest(changed=changed):
                data = dict(self.data, events=[*self.data["events"], dict(self.data["events"][0], **changed)])
                with self.assertRaises(ValueError):
                    module.reconcile(data)

    def test_duplicate_field_rejected_and_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            incoming = path / "input.json"
            output = path / "out.json"
            incoming.write_text('{"paid":[],"paid":[]}', encoding="utf-8")
            cmd = [sys.executable, "-B", str(ROOT / "reconcile.py"), "--input", str(incoming), "--output", str(output)]
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
            incoming.write_text(json.dumps(self.data), encoding="utf-8")
            output.write_text("saved", encoding="utf-8")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "saved")

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("subtitle_notes", ROOT / "convert.py")
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


class SubtitleTests(unittest.TestCase):
    def test_demo_and_bom_crlf(self):
        source = (ROOT / "demo.txt").read_text(encoding="utf-8")
        expected = (ROOT / "expected.txt").read_text(encoding="utf-8")
        self.assertEqual(notes.convert(source), expected)
        self.assertEqual(notes.convert("\ufeff" + source.replace("\n", "\r\n")), expected)

    def test_timing_precision_text_and_overlapping(self):
        data = ("007\n99:59:59,001 --> 100:00:00,001\n  甲 <i>乙</i>  \n123\n\n"
                "9\n99:59:59,001 --> 100:00:00,250\n丙\n")
        result = notes.convert(data)
        self.assertIn("[007 | 99:59:59,001 → 100:00:00,001]\n  甲 <i>乙</i>  \n123", result)
        self.assertIn("[9 | 99:59:59,001 → 100:00:00,250]", result)

    def test_empty_and_invalid_timings(self):
        for data in ["", "1", "1\n00:00:00,000 --> 00:00:01,000\n", "1\n00:60:00,000 --> 01:00:01,000\n甲",
                     "1\n00:00:00.000 --> 00:00:01.000\n甲", "1\n00:00:01,000 --> 00:00:01,000\n甲",
                     "0\n00:00:00,000 --> 00:00:01,000\n甲"]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                notes.convert(data)

    def test_order_and_missing_separator(self):
        a = "1\n00:00:02,000 --> 00:00:05,000\n甲"
        for tail in ["\n\n2\n00:00:01,000 --> 00:00:04,000\n乙", "\n\n1\n00:00:02,000 --> 00:00:04,000\n乙",
                     "\n2\n00:00:02,000 --> 00:00:04,000\n乙"]:
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                notes.convert(a + tail)

    def test_cli_preserves_data_and_refuses_invalid_encoding(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "captions.srt", Path(d) / "notes.txt"
            cmd = [sys.executable, "-B", "-X", "utf8", str(ROOT / "convert.py"),
                   "--input", str(src), "--output", str(out)]
            src.write_bytes(b"\xff\xfe")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse(out.exists())
            source = (ROOT / "demo.txt").read_text(encoding="utf-8").replace("\n", "\r\n")
            src.write_bytes(source.encode("utf-8-sig"))
            original = src.read_bytes()
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(out.read_text(encoding="utf-8"), (ROOT / "expected.txt").read_text(encoding="utf-8"))
            out.write_bytes(b"KEEP")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(out.read_bytes(), b"KEEP")
            self.assertEqual(src.read_bytes(), original)

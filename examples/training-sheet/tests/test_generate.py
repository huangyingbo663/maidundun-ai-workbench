import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("training_sheet", ROOT / "generate.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class Sheets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.in_article = False
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "article":
            self.parts.append([])
            self.in_article = True

    def handle_endtag(self, tag):
        if tag == "article":
            self.in_article = False

    def handle_data(self, data):
        if self.in_article:
            self.parts[-1].append(data)


class TestSheet(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "demo.json").read_text(encoding="utf-8"))

    def test_demo_and_answers(self):
        result = module.render(self.data)
        self.assertEqual(result, (ROOT / "expected.html").read_text(encoding="utf-8"))
        parser = Sheets()
        parser.feed(result)
        self.assertEqual(len(parser.parts), 2)
        practice, review = ["".join(p) for p in parser.parts]
        self.assertIn(self.data["submission"], practice)
        self.assertIn(self.data["checks"][0], review)
        self.assertNotIn(self.data["transfer"]["expected"], practice)
        self.assertIn(self.data["transfer"]["expected"], review)

    def test_changed_material_is_plain_text(self):
        self.data["title"] = "任务 <b>甲</b> & 乙"
        self.data["materials"] = ['改版“南门”与 "八号桌"']
        parser = Sheets()
        parser.feed(module.render(self.data))
        practice = "".join(parser.parts[0])
        self.assertIn(self.data["title"], practice)
        self.assertIn(self.data["materials"][0], practice)
        self.assertNotIn("b", parser.tags)
        self.assertNotIn("原邀请函", practice)

    def test_learner_cli_omits_full_review_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "learner.html"
            cmd = [sys.executable, "-B", str(ROOT / "generate.py"), "--input", str(ROOT / "demo.json"),
                   "--output", str(output), "--audience", "learner"]
            subprocess.run(cmd, check=True, capture_output=True)
            source = output.read_text(encoding="utf-8")
            page = Sheets()
            page.feed(source)
            self.assertEqual(len(page.parts), 1)
            self.assertIn(self.data["submission"], "".join(page.parts[0]))
            for answer in [*self.data["checks"], *self.data["transfer"].values()]:
                self.assertNotIn(answer, source)
            self.assertNotIn("review-title", source)

    def test_invalid_forms(self):
        for patch in ({"objective": "  "}, {"steps": []}, {"checks": "重做"},
                      {"materials": ["有效", 2]}, {"transfer": {"variation": "换题"}},
                      {"goal": "多余字段"}, {"prompt": "含\x00控制符"}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    module.render(dict(self.data, **patch))
        del self.data["submission"]
        with self.assertRaises(ValueError):
            module.render(self.data)

    def test_cli_duplicate_missing_file_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            incoming = directory / "task.json"
            output = directory / "sheet.html"
            cmd = [sys.executable, "-B", str(ROOT / "generate.py"), "--input", str(incoming),
                   "--output", str(output)]
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
            encoded = json.dumps(self.data)
            incoming.write_text('{"title":"重复",'+encoded[1:], encoding="utf-8")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
            incoming.write_text(encoded, encoding="utf-8-sig")
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), module.render(self.data))
            output.write_text("保留", encoding="utf-8")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "保留")


if __name__ == "__main__":
    unittest.main()

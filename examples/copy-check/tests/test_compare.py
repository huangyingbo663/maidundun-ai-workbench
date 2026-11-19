import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("copy_check", ROOT / "compare.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class CopyCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.copy = self.root / "original", self.root / "duplicate"
        self.source.mkdir()
        self.copy.mkdir()
        self.output = self.root / "report.json"

    def test_packaged_example(self):
        code = tool.run(ROOT / "demo/source", ROOT / "demo/copy", self.output)
        self.assertEqual(code, 0)
        self.assertEqual(self.output.read_bytes(), (ROOT / "expected.json").read_bytes())

    def test_changed_missing_extra_and_empty(self):
        for side in [self.source, self.copy]:
            (side / "part").mkdir()
            (side / "part/empty.txt").write_bytes(b"")
        (self.source / "card.txt").write_bytes(b"ABCD")
        (self.copy / "card.txt").write_bytes(b"ABCE")
        (self.source / "only-here.txt").write_bytes(b"X")
        (self.copy / ".extra").write_bytes(b"")
        self.assertEqual(tool.run(self.source, self.copy, self.output), 1)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"], {"same": 1, "missing": 1, "extra": 1, "changed": 1})
        self.assertEqual(report["result"], "different")
        rows = {item["path"]: item for item in report["files"]}
        self.assertEqual(list(rows), sorted(rows))
        self.assertEqual(rows["card.txt"]["source"]["sha256"], hashlib.sha256(b"ABCD").hexdigest())
        self.assertEqual(rows["card.txt"]["copy"]["bytes"], 4)
        self.assertEqual(rows["part/empty.txt"]["source"]["sha256"], hashlib.sha256(b"").hexdigest())
        self.assertIsNone(rows["only-here.txt"]["copy"])
        self.assertIsNone(rows[".extra"]["source"])
        self.assertNotIn(str(self.root), self.output.read_text(encoding="utf-8"))

    def test_empty_trees_require_attention(self):
        (self.source / "empty-dir").mkdir()
        self.assertEqual(tool.run(self.source, self.copy, self.output), 1)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8"))["result"], "empty")

    def test_directory_boundaries_and_existing_report(self):
        child = self.source / "nested"
        child.mkdir()
        for a, b, out in [(self.source, self.source, self.output), (child, self.source, self.output),
                          (self.source, child, self.output), (self.source, self.copy, child / "bad.txt"),
                          (self.source, self.copy, self.copy / "bad.txt")]:
            with self.subTest(a=a, b=b, out=out), self.assertRaises(ValueError):
                tool.run(a, b, out)
            self.assertFalse(out.exists())
        self.output.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            tool.run(self.source, self.copy, self.output)
        self.assertEqual(self.output.read_bytes(), b"keep")

    def test_block_link_or_junction(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "untouched.txt").write_bytes(b"private sample")
        link = self.copy / "linked"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            tool.run(self.source, self.copy, self.output)
        with self.assertRaises(ValueError):
            tool.run(link, self.source, self.output)
        with self.assertRaises(ValueError):
            tool.run(self.source, outside, link / "report.json")
        self.assertFalse(self.output.exists())
        self.assertEqual((outside / "untouched.txt").read_bytes(), b"private sample")

    def test_detect_change_while_hashing(self):
        src = self.source / "brief.txt"
        src.write_bytes(b"first")
        shutil.copyfile(src, self.copy / src.name)
        real_hash = hashlib.file_digest
        def change_after_read(reader, algorithm):
            digest = real_hash(reader, algorithm)
            if Path(reader.name) == src:
                src.write_bytes(b"new and longer")
            return digest
        with mock.patch.object(hashlib, "file_digest", change_after_read), self.assertRaises(ValueError):
            tool.run(self.source, self.copy, self.output)
        self.assertFalse(self.output.exists())

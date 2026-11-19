"""Run from this directory with python -B -X utf8 -m unittest discover -s ."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from plan import PlanError, board, unique_keys, write_board


HERE = Path(__file__).resolve().parent


class WorkBriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(HERE / "materials", self.root / "materials")
        self.plan = json.loads((HERE / "sample.json").read_text(encoding="utf8"))
        self.facts, self.copy, self.layout = self.plan["tasks"]
        self.file = self.root / self.facts["output"]

    def report(self):
        return board(self.plan, self.root)[0]

    def copy_receipt(self):
        data = "咨询台领取；入口旁阅读区体验；离场前交回咨询台。\n".encode()
        (self.root / self.copy["output"]).write_bytes(data)
        self.copy.update(stage="submitted", review={
            "reviewer": "checker", "decision": "pass", "criterion": self.copy["criterion"],
            "checked": "文案逐项对得上活动说明。", "sha256": hashlib.sha256(data).hexdigest(),
            "inputs": {"facts": self.facts["review"]["sha256"]},
        })

    def test_sample_is_exact_board(self):
        self.assertEqual(self.report(), (HERE / "expected.md").read_text(encoding="utf8"))
        self.assertIn("facts · 已验收", self.report())
        self.assertIn("copy · 可开工", self.report())
        self.assertIn("layout · 等前置", self.report())

    def test_changed_or_missing_evidence_blocks_dependents(self):
        self.file.write_text("已修改", encoding="utf8")
        self.assertIn("facts · 待复核", self.report())
        self.assertIn("copy · 等前置", self.report())
        self.file.unlink()
        self.assertIn("facts · 待补产物", self.report())

    def test_empty_whitespace_and_unreadable_drafts(self):
        for data in (b"", b" \n\t", b"\xff\xfe\xaf", b"garbled\x00"):
            with self.subTest(data=data):
                self.file.write_bytes(data)
                self.facts["review"]["sha256"] = hashlib.sha256(data).hexdigest()
                self.assertIn("facts · 待补产物", self.report())
                self.assertIn("copy · 等前置", self.report())

    def test_receipt_required_and_reviewer_can_request_changes(self):
        self.facts["review"]["decision"] = "revise"
        self.facts["review"]["checked"] = "归还地点需要确认。"
        self.assertIn("facts · 需返工", self.report())
        self.assertIn("copy · 等前置", self.report())
        self.facts["review"] = None
        self.assertIn("facts · 待复核", self.report())

    def test_wrong_reviewer_or_unknown_verdict(self):
        receipt = self.facts["review"]
        receipt["reviewer"] = self.facts["writer"]
        with self.assertRaisesRegex(PlanError, "另一位复核员"):
            self.report()
        receipt["reviewer"] = "checker"
        receipt["decision"] = "unknown"
        with self.assertRaisesRegex(PlanError, "验收决定"):
            self.report()

    def test_revised_acceptance_criterion_requires_review(self):
        self.facts["criterion"] = "增加无障碍入口指引。"
        self.assertIn("facts · 待复核", self.report())

    def test_approved_copy_unlocks_layout_and_stale_source_closes_it(self):
        self.copy_receipt()
        self.assertIn("layout · 可开工", self.report())
        data = self.file.read_bytes() + "补充了体验细节。\n".encode()
        self.file.write_bytes(data)
        self.facts["review"]["sha256"] = hashlib.sha256(data).hexdigest()
        report = self.report()
        self.assertIn("facts · 已验收", report)
        self.assertIn("copy · 待复核", report)
        self.assertIn("layout · 等前置", report)

    def test_other_writer_is_required_only_for_same_artifact(self):
        self.copy["writer"] = self.layout["writer"]
        self.assertIn("copy · 可开工", self.report())
        self.layout["output"] = self.copy["output"].upper().replace("MATERIALS/", "materials/")
        with self.assertRaisesRegex(PlanError, "同时认领"):
            self.report()

    def test_parent_output_cannot_be_another_output_directory(self):
        self.layout["output"] = self.copy["output"] + "/page.md"
        with self.assertRaisesRegex(PlanError, "分别用作"):
            self.report()

    def test_paths_with_ambiguous_or_external_components(self):
        for value in ("../other.md", "materials/../other.md", "materials//empty.md",
                      "materials/a./x.md", "materials/CON.txt", "materials/a\\other.md",
                      "materials/folder./x.md", "materials/test~1.md", "materials/.md",
                      "materials/Ｃ.md", "materials/foo:meta.md", "materials/page.png"):
            with self.subTest(value=value), self.assertRaises(PlanError):
                self.copy["output"] = value
                self.report()

    def test_cycle_unknown_dependency_duplicate_task_or_field(self):
        self.facts["needs"] = ["layout"]
        self.facts["review"] = None
        with self.assertRaisesRegex(PlanError, "成环"):
            self.report()
        self.facts["needs"] = ["missing"]
        with self.assertRaisesRegex(PlanError, "未登记"):
            self.report()
        self.facts["needs"] = []
        self.layout["id"] = self.copy["id"]
        with self.assertRaisesRegex(PlanError, "编号重复"):
            self.report()
        with self.assertRaisesRegex(PlanError, "重复字段"):
            json.loads('{"tasks":[],"tasks":[]}', object_pairs_hook=unique_keys)

    def test_inputs_must_cover_all_and_only_declared_dependencies(self):
        self.copy_receipt()
        self.copy["review"]["inputs"] = {}
        with self.assertRaisesRegex(PlanError, "列全"):
            self.report()

    def test_working_task_is_not_offered_to_another_writer(self):
        self.copy["stage"] = "working"
        self.assertIn("copy · 制作中", self.report())

    def test_cli_from_another_directory_and_no_overwrite(self):
        target = self.root / "report.md"
        command = [sys.executable, "-B", "-X", "utf8", str(HERE / "plan.py"),
                   str(HERE / "sample.json"), "--out", str(target)]
        self.assertEqual(subprocess.run(command, cwd=self.root, capture_output=True).returncode, 0)
        self.assertEqual(target.read_bytes(), (HERE / "expected.md").read_bytes())
        target.write_bytes(b"keep")
        self.assertNotEqual(subprocess.run(command, cwd=self.root, capture_output=True).returncode, 0)
        self.assertEqual(target.read_bytes(), b"keep")

    def test_error_does_not_create_board_or_claimed_source(self):
        source = self.root / "sample.json"
        target = self.root / self.copy["output"]
        source.write_text(json.dumps(self.plan), encoding="utf8")
        with self.assertRaisesRegex(PlanError, "已认领"):
            write_board(source, target)
        self.assertFalse(target.exists())
        self.copy["needs"] = ["missing"]
        source.write_text(json.dumps(self.plan), encoding="utf8")
        with self.assertRaises(PlanError):
            write_board(source, self.root / "board.md")
        self.assertFalse((self.root / "board.md").exists())

    def test_hard_link_is_not_an_independent_artifact(self):
        (self.root / self.copy["output"]).hardlink_to(self.file)
        with self.assertRaisesRegex(PlanError, "独立"):
            self.report()


if __name__ == "__main__":
    unittest.main()

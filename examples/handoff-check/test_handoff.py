from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import check_handoff as checker


HERE = Path(__file__).resolve().parent


class HandoffTests(unittest.TestCase):
    def setUp(self):
        space = tempfile.TemporaryDirectory()
        self.addCleanup(space.cleanup)
        self.root = Path(space.name)
        self.input = self.root / "sample.json"
        self.out = self.root / "result.json"
        shutil.copyfile(HERE / "sample.json", self.input)
        for folder in ("artifacts", "reviews"):
            shutil.copytree(HERE / folder, self.root / folder)
        self.guide = self.root / "artifacts" / "guide.md"
        self.receipt = self.root / "reviews" / "guide.json"

    def adjust(self, path, transform):
        data = checker.read_json(path)
        transform(data)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def rows(self):
        return checker.handoff(self.input)[0]["items"]

    def run_tool(self, output=None):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return checker.main(["--input", str(self.input), "--output", str(output or self.out)])

    def test_reference_card_has_one_verified_and_two_open(self):
        self.assertEqual(self.run_tool(), 0)
        result = checker.read_json(self.out)
        self.assertEqual(result, checker.read_json(HERE / "expected.json"))
        self.assertIs(result["can_close"], False)
        self.assertEqual([r["state"] for r in result["items"]], ["verified", "blocked", "waiting_human"])
        self.assertEqual(result["items"][0]["actual_sha256"], sha256(self.guide.read_bytes()).hexdigest())

    def test_changed_file_needs_new_review(self):
        self.guide.write_bytes(self.guide.read_bytes() + b"\n")
        changed = self.rows()[0]
        self.assertEqual((changed["state"], changed["next_owner"]), ("changed", "checker"))
        self.adjust(self.receipt, lambda doc: doc.update(sha256=sha256(self.guide.read_bytes()).hexdigest(),
                                                         observation="复核人已重新读过修订版。"))
        self.assertEqual(self.rows()[0]["state"], "verified")

    def test_missing_or_empty_artifact_overrides_old_receipt(self):
        self.guide.write_bytes(b"")
        self.assertEqual(self.rows()[0]["state"], "missing_file")
        self.guide.unlink()
        self.assertEqual(self.rows()[0]["state"], "missing_file")

    def test_missing_receipt_requires_independent_review(self):
        self.receipt.unlink()
        row = self.rows()[0]
        self.assertEqual((row["state"], row["next_owner"]), ("needs_review", "checker"))

    def test_malformed_receipt_cannot_approve(self):
        self.receipt.write_text("{", encoding="utf-8")
        self.assertEqual(self.rows()[0]["state"], "needs_review")

    def test_receipt_is_bound_to_task_actor_path_criterion_and_decision(self):
        original = self.receipt.read_bytes()
        for key, value in (("task", "elsewhere"), ("owner", "other"), ("reviewer", "writer"),
                           ("artifact", "artifacts/other.md"), ("criterion", "换过的标准"),
                           ("sha256", "bad"), ("decision", "na"), ("observation", " ")):
            with self.subTest(key=key):
                self.receipt.write_bytes(original)
                self.adjust(self.receipt, lambda doc: doc.update({key: value}))
                self.assertEqual(self.rows()[0]["state"], "needs_review")

    def test_changes_requested_go_to_writer(self):
        self.adjust(self.receipt, lambda doc: doc.update(decision="changes_requested", observation="重写归还步骤。"))
        row = self.rows()[0]
        self.assertEqual((row["state"], row["next_owner"], row["reason"]), ("fix_requested", "writer", "重写归还步骤。"))

    def test_site_report_needs_its_own_approval(self):
        task = checker.read_json(self.input)["tasks"][2]
        (self.root / task["artifact"]).write_bytes("站在入口，能看到三步说明。".encode())
        self.assertEqual(self.rows()[2]["state"], "needs_review")
        shutil.copyfile(self.receipt, self.root / task["receipt"])
        self.assertEqual(self.rows()[2]["state"], "needs_review")
        self.adjust(self.root / task["receipt"],
                    lambda doc: doc.update(task="onsite", owner="host", criterion=task["criterion"],
                                           gate="human", artifact=task["artifact"], sha256=self.rows()[2]["actual_sha256"],
                                           observation="核对了现场记录的观察位置和可见内容。"))
        self.assertEqual(self.rows()[2]["state"], "verified")

    def test_blocker_must_be_explicitly_resolved(self):
        self.adjust(self.input, lambda doc: doc["tasks"][1].update(blocker=None))
        self.assertEqual(self.rows()[1]["state"], "missing_file")

    def test_gate_change_invalidates_review_for_same_file(self):
        self.adjust(self.input, lambda doc: doc["tasks"][0].update(gate="human"))
        self.assertEqual(self.rows()[0]["state"], "needs_review")
        self.adjust(self.receipt, lambda doc: doc.update(gate="human", observation="复核人另核现场观察记录。"))
        self.assertEqual(self.rows()[0]["state"], "verified")

    def test_whitespace_is_never_accepted_even_with_approved_hash(self):
        for gate, expected in (("human", "waiting_human"), ("file", "missing_file")):
            for blank in ("\ufeff \t\n\u3000", " \n" * 65536):
                with self.subTest(gate=gate, size=len(blank)):
                    self.guide.write_bytes(blank.encode("utf-8"))
                    self.adjust(self.input, lambda doc: doc["tasks"][0].update(gate=gate))
                    self.adjust(self.receipt, lambda doc: doc.update(gate=gate, sha256=sha256(self.guide.read_bytes()).hexdigest()))
                    self.assertEqual(self.rows()[0]["state"], expected)

    def test_text_requires_utf8_and_binary_can_be_reviewed(self):
        self.guide.write_bytes(bytes([255, 216, 255]))
        self.assertEqual(self.rows()[0]["state"], "missing_file")
        self.guide.rename(self.guide.with_suffix(".bin"))
        self.adjust(self.input, lambda doc: doc["tasks"][0].update(artifact="artifacts/guide.bin"))
        self.adjust(self.receipt, lambda doc: doc.update(artifact="artifacts/guide.bin", sha256=self.rows()[0]["actual_sha256"]))
        self.assertEqual(self.rows()[0]["state"], "verified")

    def test_can_close_only_if_all_rows_verified(self):
        self.adjust(self.input, lambda doc: doc.update(tasks=doc["tasks"][:1]))
        self.assertTrue(checker.handoff(self.input)[0]["can_close"])

    def test_invalid_or_aliased_paths_and_roles(self):
        original = self.input.read_bytes()
        for key, value in (("artifact", "../guide.md"), ("artifact", "artifacts/../guide.md"),
                           ("artifact", "artifacts/CON.txt"), ("artifact", "artifacts//notes"),
                           ("artifact", "artifacts/guide.md:part"), ("receipt", "artifacts/x.md"),
                           ("artifact", "artifacts/GUIDE.md"), ("owner", "checker"), ("id", "copy")):
            with self.subTest(key=key, value=value):
                self.input.write_bytes(original)
                self.adjust(self.input, lambda doc: doc["tasks"][1].update({key: value}))
                with self.assertRaises(checker.Invalid):
                    self.rows()

    def test_duplicate_keys_and_empty_plans_fail(self):
        self.input.write_text('{"version":1,"version":1}', encoding="utf-8")
        with self.assertRaises(checker.Invalid):
            self.rows()
        self.input.write_text('{"version":1,"goal":"test","tasks":[]}', encoding="utf-8")
        with self.assertRaises(checker.Invalid):
            self.rows()

    def test_hardlinked_evidence_rejected(self):
        os.link(self.guide, self.root / "second-name.md")
        with self.assertRaises(checker.Invalid):
            self.rows()

    def test_future_artifact_and_directory_conflict_in_either_order(self):
        original = self.input.read_bytes()
        for reverse in (False, True):
            self.input.write_bytes(original)
            data = checker.read_json(self.input)
            data["tasks"][2]["artifact"] = "artifacts/LAYOUT.md/site-note.md"
            if reverse:
                data["tasks"].reverse()
            self.input.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(checker.Invalid):
                self.rows()

    def test_output_cannot_reserve_future_artifact_parent(self):
        self.adjust(self.input, lambda doc: doc["tasks"][2].update(artifact="artifacts/site/observation.md"))
        reserved = self.root / "artifacts" / "site"
        with self.assertRaises(SystemExit):
            self.run_tool(output=reserved)
        self.assertFalse(reserved.exists())

    def test_retry_keeps_existing_result_and_sources(self):
        self.run_tool()
        first = self.out.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_tool()
        self.assertEqual(self.out.read_bytes(), first)
        reserved = self.root / "artifacts" / "site-note.md"
        with self.assertRaises(SystemExit):
            self.run_tool(output=reserved)
        self.assertFalse(reserved.exists())
        self.assertEqual(self.run_tool(output=self.root / "second.json"), 0)
        self.assertEqual((self.root / "second.json").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()

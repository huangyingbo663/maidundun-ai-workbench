"""Offline public-package maintenance. No HTTP, secrets, timers, or remote Git commands.

SPDX-License-Identifier: MIT
Copyright (c) 2026 麦囤囤·AI工坊
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote, urlsplit
import zipfile

RECEIPT = "public-export-receipt.json"
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ".js", ".svg", ".csv", ".ps1", ".sh", ".lock"}
SKIPS = [
    "GitHub Actions manual and real schedule triggers: requires live repository evidence",
    "Dependency alerts, workflow disabled state and last cloud success: requires live repository review",
    "External links and model documentation changes: not requested over the network by this offline tool",
    "Remote Releases, Issues and attachments backup: not included in local Git/package recovery",
    "Content aesthetics, rights and human acceptance: not replaced by these deterministic checks",
]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def text_lf(data):
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

def text_member(name):
    return Path(name).suffix.lower() in TEXT_SUFFIXES or Path(name).name in {"LICENSE", "NOTICE", ".gitignore", ".gitattributes", ".env.example"}

def matches_receipt(name, data, row):
    if "sha256_lf" in row:
        if not text_member(name) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256_lf"]):
            raise ValueError("sha256_lf requires a known UTF-8 text file and a valid SHA")
        return digest(text_lf(data)) == row["sha256_lf"]
    return digest(data) == row["sha256"]

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("nonempty POSIX relative path required")
    p = PurePosixPath(value)
    if p.is_absolute() or p.as_posix() != value or any(x in (".", "..") for x in p.parts):
        raise ValueError("unsafe relative path")
    if any(re.search(r'[<>:"|?*\x00-\x1f]', x) or x.endswith((".", " ")) for x in p.parts):
        raise ValueError("unsafe path component")
    if any(x.casefold() in (".git", "__pycache__") for x in p.parts):
        raise ValueError("history/cache not a package member")
    return p

def safe_file(root, name):
    rel = relative(name)
    p = root.joinpath(*rel.parts)
    for candidate in [p, *list(p.parents)[:len(rel.parts)-1]]:
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("symlink or junction is forbidden")
    resolved = p.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("file must be inside package")
    # Match Linux case semantics even when testing on Windows.
    current = root
    for part in rel.parts:
        if part not in {x.name for x in current.iterdir()}:
            raise ValueError("path case does not match actual file")
        current = current / part
    return resolved

def finding(report, kind, path, message, line=None):
    row = {"id": digest((kind + "|" + path + "|" + message).encode())[:16],
           "kind": kind, "path": path, "message": message}
    if line is not None:
        row["line"] = line
    report["findings"].append(row)

class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "name" in attrs:
            self.ids.add(attrs["name"])
        for key in ("href", "src", "poster"):
            if attrs.get(key):
                self.links.append((attrs[key], self.getpos()[0]))

def clean_markdown(text):
    lines = text.splitlines()
    in_fence = False
    output = []
    for line in lines:
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            output.append("")
        else:
            output.append("" if in_fence else re.sub(r"`[^`]*`", "", line))
    return "\n".join(output)

def document(text, suffix):
    cleaned = clean_markdown(text) if suffix == ".md" else text
    parser = Tags()
    parser.feed(cleaned)
    links, ids = parser.links, parser.ids
    if suffix == ".md":
        counts = {}
        for line in cleaned.splitlines():
            m = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
            if m:
                name = m[1].lower().replace(" ", "-")
                name = "".join(c for c in name if c in "-_" or unicodedata.category(c)[0] in "LN")
                count = counts.get(name, 0)
                counts[name] = count + 1
                ids.add(name + ("-" + str(count) if count else ""))
        # Deliberately supports ordinary inline and reference links, not arbitrary Markdown extensions.
        for n, line in enumerate(cleaned.splitlines(), 1):
            for m in re.finditer(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)", line):
                links.append((m[1] or m[2], n))
            m = re.match(r"^\s{0,3}\[[^\]]+\]:\s*<?([^\s>]+)>?", line)
            if m:
                links.append((m[1], n))
    return links, ids

def link_checks(root, files, report):
    documents = {}
    for name in files:
        if Path(name).suffix.lower() in (".md", ".html"):
            try:
                documents[name] = document(safe_file(root, name).read_text(encoding="utf-8-sig"), Path(name).suffix.lower())
            except (OSError, ValueError, UnicodeError) as exc:
                finding(report, "document", name, type(exc).__name__)
    count = 0
    external = set()
    for name, (links, _) in documents.items():
        for target, line in links:
            try:
                parsed = urlsplit(target)
                if parsed.scheme in ("https", "http") or parsed.netloc:
                    external.add(target)
                    continue
                if parsed.scheme in ("mailto", "tel", "data"):
                    continue
                if parsed.scheme or "\\" in target:
                    raise ValueError("unsupported or machine-local URL")
                raw = unquote(parsed.path)
                base = root if raw.startswith("/") else root / PurePosixPath(name).parent
                # Normalize dot segments lexically; resolve() on Windows erases wrong-case evidence.
                candidate = Path(os.path.normpath(base / raw.lstrip("/"))) if raw else root / name
                if not candidate.is_relative_to(root):
                    raise ValueError("link escapes package")
                rel = candidate.relative_to(root).as_posix()
                if candidate.is_dir():
                    rel = (candidate / "index.html").relative_to(root).as_posix()
                safe_file(root, rel)
                if rel not in files and rel != RECEIPT:
                    raise ValueError("link points outside approved file inventory")
                if parsed.fragment and Path(rel).suffix.lower() in (".md", ".html"):
                    if rel not in documents:
                        raise ValueError("anchor target document unavailable")
                    if unquote(parsed.fragment) not in documents[rel][1]:
                        raise ValueError("missing local anchor")
                count += 1
            except (OSError, ValueError) as exc:
                # Include relative target for actionable reports; no file contents or tokens.
                message = "missing or unreadable local target" if isinstance(exc, OSError) else str(exc)
                finding(report, "local_link", name, message + ": " + target, line)
    report["links"] = {"local_checked": count, "external_not_fetched": len(external)}

def sample_environment():
    # Do not inherit generation API keys, GitHub tokens or arbitrary PYTHONPATH.
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return env

def sample_checks(root, config, files, out, report):
    samples = config.get("samples")
    if not isinstance(samples, list) or not samples:
        finding(report, "config", "maintenance.json", "at least one real offline sample is required")
        return
    report["samples"] = []
    seen = set()
    for sample in samples:
        sid = sample.get("id", "")
        result = {"id": sid, "status": "failed"}
        report["samples"].append(result)
        try:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", sid) or sid in seen:
                raise ValueError("unique simple sample id required")
            seen.add(sid)
            entry = sample["entrypoint"]
            if entry not in files or Path(entry).suffix != ".py":
                raise ValueError("sample entrypoint must be an inventoried Python file")
            safe_file(root, entry)
            expected = sample["expected_outputs"]
            if not isinstance(expected, list) or not expected:
                raise ValueError("sample needs expected output SHA assertions")
            timeout = sample.get("timeout_seconds", 30)
            if not isinstance(timeout, int) or not 1 <= timeout <= 120:
                raise ValueError("sample timeout must be 1..120 seconds")
            work = out / "samples" / sid
            work.mkdir(parents=True, exist_ok=False)
            args = sample.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError("sample args must be a string array")
            sample_cwd = work if sample.get("isolated_cwd") is True else root
            argv = [sys.executable, "-B", "-X", "utf8", str(safe_file(root, entry))] + [a.replace("{output}", str(work)).replace("{root}", str(root)) for a in args]
            done = subprocess.run(argv, cwd=sample_cwd, env=sample_environment(), capture_output=True, timeout=timeout)
            result["returncode"] = done.returncode
            result["stdout_sha256"] = digest(done.stdout)
            result["stderr_sha256"] = digest(done.stderr)
            if done.returncode:
                raise ValueError("sample exited nonzero (inspect reviewed sample locally; stdout is not echoed)")
            result["outputs"] = []
            for row in expected:
                output_file = safe_file(work, row["path"])
                actual = digest(output_file.read_bytes())
                comparison = actual
                comparison_format = row.get("format", "bytes")
                if comparison_format == "canonical-json":
                    comparison = digest(json.dumps(read_json(output_file), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
                elif comparison_format == "text-lf":
                    comparison = digest(text_lf(output_file.read_bytes()))
                elif comparison_format != "bytes":
                    raise ValueError("unknown expected output comparison format")
                expected_sha = row.get("sha256")
                if "reference" in row:
                    reference = row["reference"]
                    if reference not in files:
                        raise ValueError("expected reference is not registered in package")
                    reference_file = safe_file(root, reference)
                    reference_bytes = reference_file.read_bytes()
                    if comparison_format == "canonical-json":
                        reference_bytes = json.dumps(read_json(reference_file), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                    elif comparison_format == "text-lf":
                        reference_bytes = text_lf(reference_bytes)
                    expected_sha = digest(reference_bytes)
                if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                    raise ValueError("expected output requires a valid SHA or registered reference")
                result["outputs"].append({"path": row["path"], "sha256": actual, "comparison_format": comparison_format, "comparison_sha256": comparison})
                if comparison != expected_sha:
                    raise ValueError("sample output SHA mismatch: " + row["path"])
            result["status"] = "passed"
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
            finding(report, "sample", sid, str(exc) if not isinstance(exc, subprocess.TimeoutExpired) else "sample timeout")

def inventory(root, report):
    receipt = read_json(safe_file(root, RECEIPT))
    if receipt.get("schema_version") != 1 or receipt.get("status") != "exported" or receipt.get("network_used") is not False:
        raise ValueError("expected stage_public v3 exported receipt")
    rows = receipt["files"]
    if not rows or receipt.get("file_count") != len(rows):
        raise ValueError("receipt file count invalid")
    files = {}
    folded = set()
    for row in rows:
        name = relative(row["destination"]).as_posix()
        if name == RECEIPT or name.casefold() in folded:
            raise ValueError("duplicate/reserved receipt member")
        folded.add(name.casefold())
        files[name] = row
        try:
            data = safe_file(root, name).read_bytes()
            row["_observed_sha256"] = digest(data)
            if not matches_receipt(name, data, row):
                finding(report, "integrity", name, "file SHA differs from export receipt")
        except (OSError, ValueError) as exc:
            finding(report, "integrity", name, type(exc).__name__ + ": missing or unsafe approved file")
    actual_files = set()
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) == root and d == ".git")]
        for d in list(dirs):
            p = Path(parent) / d
            if p.is_symlink() or p.is_junction():
                finding(report, "inventory", p.relative_to(root).as_posix(), "linked directory forbidden")
                dirs.remove(d)
        for name in names:
            actual_files.add((Path(parent) / name).relative_to(root).as_posix())
    for name in sorted(actual_files - set(files) - {RECEIPT}):
        finding(report, "inventory", name, "file absent from approved receipt")
    report["inventory"] = {"approved_files": len(files), "receipt_sha256": digest((root / RECEIPT).read_bytes())}
    return files

def check(root, config_name, out):
    report = {"schema_version": 1, "status": "failed", "findings": [], "not_verified": SKIPS,
              "network_used": False, "remote_write": False, "at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        files = inventory(root, report)
        config = read_json(safe_file(root, config_name))
        if config.get("schema_version") != 1 or config_name not in files:
            raise ValueError("maintenance config must be inventoried schema version 1")
        required = config.get("required_files")
        if not isinstance(required, list) or not required:
            raise ValueError("nonempty required_files needed")
        for name in required:
            if name not in files:
                finding(report, "required", name, "required file is absent from approved inventory")
        link_checks(root, files, report)
        # Never execute a sample when its package differs from the approved hashes.
        if any(x["kind"] in ("integrity", "inventory", "required") for x in report["findings"]):
            report["samples_skipped"] = "package integrity failed"
        else:
            sample_checks(root, config, files, out, report)
            # Reviewed samples must not mutate source material while producing outputs.
            for name, row in files.items():
                if digest(safe_file(root, name).read_bytes()) != row["_observed_sha256"]:
                    finding(report, "integrity", name, "sample changed an approved input file")
            if digest(safe_file(root, RECEIPT).read_bytes()) != report["inventory"]["receipt_sha256"]:
                finding(report, "integrity", RECEIPT, "sample changed the public receipt")
        report["status"] = "passed" if not report["findings"] else "failed"
        return report, config, files
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        finding(report, "package", config_name, type(exc).__name__ + ": " + str(exc))
        return report, {}, {}

def git(root, *args):
    # Every caller below uses local-only Git operations; no fetch/push/remote invocation.
    done = subprocess.run(["git", "-C", str(root), *args], env=sample_environment(), capture_output=True, timeout=60)
    if done.returncode:
        raise ValueError("local Git command failed: " + args[0])
    return done.stdout.decode("utf-8", errors="replace").strip()

def recover(root, config_name, out, report, config, files):
    if report["findings"]:
        report["recovery"] = {"status": "blocked_by_checks"}
        return
    recovery = {"status": "failed", "scope": "approved public package and local Git refs, not remote service data"}
    report["recovery"] = recovery
    try:
        members = sorted([*files, RECEIPT])
        before = {name: digest(safe_file(root, name).read_bytes()) for name in members}
        archive = out / "public-package.zip"
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
            for name in members:
                z.writestr(name, safe_file(root, name).read_bytes())
        restored = out / "restored-package"
        restored.mkdir()
        with zipfile.ZipFile(archive) as z:
            if sorted(z.namelist()) != members:
                raise ValueError("archive inventory differs")
            for name in z.namelist():
                target = restored.joinpath(*relative(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
        after = {name: digest(safe_file(restored, name).read_bytes()) for name in members}
        if before != after:
            raise ValueError("restored package bytes differ")
        zip_out = out / "restored-package-check"
        zip_out.mkdir()
        zip_report, _, _ = check(restored, config_name, zip_out)
        save_report(zip_out, zip_report)
        if zip_report["status"] != "passed":
            raise ValueError("restored package checks failed")
        recovery.update(zip_sha256=digest(archive.read_bytes()), restored_files=len(after), package="passed")
        if config.get("git_restore") != "required":
            raise ValueError("monthly configuration must require a real local Git bundle restore")
        if git(root, "rev-parse", "--show-toplevel").replace("\\", "/").casefold() != str(root).replace("\\", "/").casefold():
            raise ValueError("package root must be Git root")
        if git(root, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Git worktree must be clean before recovery")
        original_head = git(root, "rev-parse", "HEAD")
        original_refs = git(root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags")
        bundle = out / "repository.bundle"
        git(root, "bundle", "create", str(bundle), "--all")
        git(root, "bundle", "verify", str(bundle))
        bare = out / "restored.git"
        git(out, "clone", "--mirror", str(bundle), str(bare))
        if git(bare, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags") != original_refs:
            raise ValueError("restored Git branch/tag refs differ")
        git(out, "clone", "--config", "core.autocrlf=false", str(bare), str(out / "restored-repository"))
        repo = out / "restored-repository"
        git(repo, "checkout", "--detach", original_head)
        if git(repo, "rev-parse", "HEAD") != original_head:
            raise ValueError("restored Git HEAD differs")
        git_out = out / "restored-repository-check"
        git_out.mkdir()
        git_report, _, _ = check(repo, config_name, git_out)
        save_report(git_out, git_report)
        if git_report["status"] != "passed":
            raise ValueError("restored Git worktree checks failed")
        recovery.update(git="passed", head=original_head, refs=original_refs.splitlines(),
                        bundle_sha256=digest(bundle.read_bytes()), status="passed")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        finding(report, "recovery", "monthly", str(exc))
        report["status"] = "failed"

def save_report(out, report):
    write_json(out / "report.json", report)
    rows = ["# Maintenance " + report["status"], "", "Offline checks only. Remote triggers and alerts remain unverified.", ""]
    rows += ["Approved files: " + str(report.get("inventory", {}).get("approved_files", 0)),
             "Local links checked: " + str(report.get("links", {}).get("local_checked", 0)), ""]
    for sample in report.get("samples", []):
        rows.append("- Sample `" + sample["id"] + "`: " + sample["status"])
    if "recovery" in report:
        recovery = report["recovery"]
        rows += ["", "Recovery: " + recovery["status"],
                 "Package: " + recovery.get("package", "not completed") + "; Git: " + recovery.get("git", "not completed")]
    rows += ["", "## Findings", ""]
    rows += ["- `" + r["id"] + "` " + r["kind"] + " — " + r["path"] + (":" + str(r["line"]) if "line" in r else "") + " — " + r["message"] for r in report["findings"]]
    if not report["findings"]:
        rows.append("No blocking local findings.")
    rows += ["", "## Not verified", ""] + ["- " + x for x in SKIPS]
    (out / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("weekly", "monthly", "register"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", default="maintenance.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        out = args.out.resolve()
        if not root.is_dir() or out.is_relative_to(root) or root.is_relative_to(out):
            raise ValueError("output must be a new separate directory outside the package")
        out.mkdir(parents=True, exist_ok=False)
        if args.mode == "register":
            receipt = read_json(safe_file(root, RECEIPT))
            if receipt.get("schema_version") != 1 or not isinstance(receipt.get("files"), list) or not receipt["files"]:
                raise ValueError("register needs an existing explicit file inventory")
            names = set()
            for row in receipt["files"]:
                name = relative(row["destination"]).as_posix()
                if name.casefold() in names or name == RECEIPT:
                    raise ValueError("duplicate or reserved inventory path")
                names.add(name.casefold())
                data = safe_file(root, name).read_bytes()
                row["sha256"] = digest(data)
                if text_member(name):
                    row["sha256_lf"] = digest(text_lf(data))
                else:
                    row.pop("sha256_lf", None)
            receipt["file_count"] = len(receipt["files"])
            receipt["status"] = "needs_review"
            receipt["hash_contract"] = "bytes-with-explicit-utf8-lf-v1"
            write_json(out / "receipt-candidate.json", receipt)
            print(json.dumps({"status": "candidate_created", "review_required": True, "source_receipt_replaced": False, "network_used": False}))
            return 0
        report, config, files = check(root, args.config, out)
        report["mode"] = args.mode
        if args.mode == "monthly":
            recover(root, args.config, out, report, config, files)
        save_report(out, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

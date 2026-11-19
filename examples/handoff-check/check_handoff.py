"""Check a frozen handoff and write a reader's next-action card."""
import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata


class Invalid(ValueError):
    pass


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid("JSON 出现重复字段。")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)


def fields(record, names):
    if not isinstance(record, dict) or set(record) != set(names.split()):
        raise Invalid("字段缺失或有多余字段，请按示例填写。")


def written(value):
    return isinstance(value, str) and bool(value.strip())


def code(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_-]*", value)


def scoped_path(base, raw, folder):
    if not isinstance(raw, str):
        raise Invalid("产物与复核记录须填相对路径。")
    parts = raw.split("/")
    if len(parts) < 2 or parts[0] != folder:
        raise Invalid("请将产物放在 artifacts/ 下，复核记录放在 reviews/ 下。")
    path = base
    for index, part in enumerate(parts):
        if (not part or unicodedata.normalize("NFKC", part) != part
                or part.startswith(".") or part.endswith(".")
                or not all(char.isalnum() or char in "_-." for char in part)
                or re.fullmatch(r"con|prn|aux|nul|com[0-9]|lpt[0-9]", part.split(".")[0], re.I)):
            raise Invalid("路径分段含无效字符或保留名称。")
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise Invalid("样例目录与文件须为普通文件和目录。")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise Invalid("路径的中间节点须为目录。")
        if index == len(parts) - 1 and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise Invalid("证据路径须指向独立的普通文件。")
    return path


def check_receipt(task, receipt, actual):
    fields(receipt, "task owner reviewer criterion gate artifact sha256 decision observation")
    for key in ("owner", "reviewer", "criterion", "gate", "artifact"):
        if receipt[key] != task[key]:
            raise Invalid("复核记录对应的人员、标准或路径与本项不一致。")
    if (receipt["task"] != task["id"] or not written(receipt["observation"])
            or not isinstance(receipt["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", receipt["sha256"])
            or receipt["decision"] not in ("approved", "changes_requested")):
        raise Invalid("复核记录须写明对应任务、文件指纹、检查结论和实际观察。")
    if actual != receipt["sha256"]:
        return "changed", "当前文件的指纹与复核版本不同，请重新打开当前文件逐项复核。"
    if receipt["decision"] == "changes_requested":
        return "fix_requested", receipt["observation"]
    return "verified", receipt["observation"]


def fingerprint(path):
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    has_content = False
    text_required = path.suffix.casefold() in (".txt", ".md", ".json", ".csv", ".html", ".xml", ".yaml", ".yml")
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(65536)
            digest.update(chunk)
            if decoder is not None:
                try:
                    characters = decoder.decode(chunk, final=not chunk)
                    has_content = has_content or any(c.isprintable() and not c.isspace() for c in characters)
                except UnicodeDecodeError:
                    has_content = not text_required
                    decoder = None
            if not chunk:
                break
    return digest.hexdigest(), has_content


def assess(task, artifact, receipt, row):
    if task["blocker"] is not None:
        return "blocked", task["blocker"]
    has_content = False
    if artifact.is_file():
        row["actual_sha256"], has_content = fingerprint(artifact)
    if not has_content:
        if task["gate"] == "human":
            return "waiting_human", "尚未取得有内容的现场观察记录，请检查文件及文本编码。"
        return "missing_file", "尚未取得有内容的任务产物，请检查文件及文本编码。"
    if not receipt.is_file():
        return "needs_review", "产物已出现，等待独立复核人写下检查结果。"
    try:
        return check_receipt(task, read_json(receipt), row["actual_sha256"])
    except (ValueError, UnicodeError, RecursionError):
        return "needs_review", "复核记录无法与本任务、人员和标准对应，请按样例重做复核记录。"


def handoff(path):
    base = path.parent
    data = read_json(path)
    fields(data, "version goal tasks")
    if (type(data["version"]) is not int or data["version"] != 1 or not written(data["goal"])
            or not isinstance(data["tasks"], list) or not data["tasks"]):
        raise Invalid("请使用版本 1，填写目标以及至少一项任务。")
    ids = set()
    paths = set()
    directories = set()
    protected = {path.resolve()}
    rows = []
    for task in data["tasks"]:
        fields(task, "id owner reviewer criterion gate artifact receipt blocker next")
        if not all(code(task[key]) for key in ("id", "owner", "reviewer")):
            raise Invalid("任务和角色代号须以小写字母开头，使用字母、数字、下划线或短横线。")
        if task["id"] in ids or task["owner"] == task["reviewer"]:
            raise Invalid("请给每项任务独立代号，并分别指定执行人与复核人。")
        ids.add(task["id"])
        if (task["gate"] not in ("human", "file") or not written(task["criterion"])
                or not written(task["next"])
                or (task["blocker"] is not None and not written(task["blocker"]))):
            raise Invalid("须填写验收标准、接班动作、关口类型以及具体阻塞原因或 null。")
        artifact = scoped_path(base, task["artifact"], "artifacts")
        receipt = scoped_path(base, task["receipt"], "reviews")
        for key, source in (("artifact", artifact), ("receipt", receipt)):
            ident = task[key].casefold()
            parents = {ancestor.as_posix() for ancestor in Path(ident).parents}
            if ident in paths or ident in directories or not parents.isdisjoint(paths):
                raise Invalid("每项任务须使用自己对应的产物和复核记录。")
            paths.add(ident)
            directories.update(parents)
            protected.add(source.resolve())
        row = {key: task[key] for key in ("id", "owner", "reviewer", "gate", "criterion", "artifact", "receipt")}
        row["actual_sha256"] = None
        state, reason = assess(task, artifact, receipt, row)
        actor, action = task["owner"], task["next"]
        if state in ("needs_review", "changed"):
            actor, action = task["reviewer"], "打开当前产物，按验收标准检查，记录指纹、观察和决定。"
        elif state == "fix_requested":
            action = "根据复核意见修订产物，交给原复核人重验。"
        elif state == "verified":
            actor, action = None, "保留这一版产物及其复核记录。"
        row.update(state=state, reason=reason, next_owner=actor, next_action=action)
        rows.append(row)
    return {"goal": data["goal"], "can_close": all(row["state"] == "verified" for row in rows),
            "items": rows}, protected


def write_new(path, report):
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(content)
        os.link(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="从当前产物和独立复核记录制作接班卡。")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report, protected = handoff(args.input)
        target = args.output.resolve()
        if any(target == source or target in source.parents or source in target.parents
               for source in protected):
            raise Invalid("请把输出另存到任务输入、产物及复核记录以外。")
        write_new(args.output, report)
    except FileExistsError:
        parser.exit(2, "结果文件已存在，请使用新文件名。\n")
    except (ValueError, RecursionError) as exc:
        parser.exit(2, f"输入无效，{exc}\n")
    except OSError:
        parser.exit(2, "无法读写文件，请核对目录、普通文件、权限及磁盘是否支持硬链接。\n")
    print("已生成接班卡。打开 JSON 查看 can_close 和每项 next_action。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

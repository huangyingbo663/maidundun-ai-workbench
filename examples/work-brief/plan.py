"""Turn a local, independently reviewed task plan into a read-only work board."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
from graphlib import CycleError, TopologicalSorter


class PlanError(ValueError):
    pass


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanError("JSON 对象含重复字段。")
        result[key] = value
    return result


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise PlanError(f"{label} 字段与 sample.json 不一致。")


def sentence(value, label):
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise PlanError(f"{label} 需要非空文字，请去掉首尾空格。")
    if any(not char.isprintable() for char in value):
        raise PlanError(f"{label} 需要单行文字。")


def handle(value, label):
    if not isinstance(value, str) or not re.fullmatch("[a-z][a-z0-9-]{0,39}", value):
        raise PlanError(f"{label} 请用小写英文字母开头，后接字母、数字或短横线。")


def digest(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise PlanError("验收记录须填写 64 位小写 SHA-256。")


def artifact(root, name):
    if not isinstance(name, str) or not name.startswith("materials/"):
        raise PlanError("产物须位于计划旁的 materials/ 目录中。")
    if not name.casefold().endswith((".md", ".txt")):
        raise PlanError("本看板的产物支持 Markdown 或纯文本文稿。")
    parts = name.split("/")
    path = root
    for index, part in enumerate(parts):
        reserved = part.split(".")[0].casefold() in {
            "con", "aux", "nul", "prn", "conin$", "conout$",
            *(f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)),
        }
        if (not part or not re.fullmatch(r"[\w .-]+", part)
                or part != unicodedata.normalize("NFKC", part)
                or part.startswith((".", " ")) or part.endswith((".", " ")) or reserved):
            raise PlanError("产物路径须使用可跨平台的普通目录和文件名。")
        path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise PlanError("产物路径包含链接。")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(info.st_mode):
                raise PlanError("产物路径中的上级项需要是普通目录。")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PlanError("产物需要是独立的普通文件。")
    return path


def validate_plan(plan, root):
    fields(plan, "goal tasks", "计划")
    sentence(plan["goal"], "goal")
    if not isinstance(plan["tasks"], list) or not plan["tasks"]:
        raise PlanError("至少填写一个任务。")
    tasks, paths, owners = {}, {}, {}
    for item in plan["tasks"]:
        fields(item, "id writer output needs criterion next stage review", "任务")
        name = item["id"]
        handle(name, "id")
        handle(item["writer"], "writer")
        for key in ("criterion", "next"):
            sentence(item[key], key)
        if name in tasks:
            raise PlanError(f"任务编号重复：{name}。")
        path = artifact(root, item["output"])
        key = item["output"].casefold()
        if key in owners:
            raise PlanError(f"{owners[key]} 和 {name} 同时认领一个产物。")
        if any(key.startswith(p + "/") or p.startswith(key + "/") for p in owners):
            raise PlanError("两项产物将同一路径分别用作文件与目录。")
        needs = item["needs"]
        if not isinstance(needs, list):
            raise PlanError("needs 需要是任务编号列表。")
        for dep in needs:
            handle(dep, "needs")
        if len(needs) != len(set(needs)):
            raise PlanError(f"{name} 的依赖重复。")
        if item["stage"] not in ("planned", "working", "submitted"):
            raise PlanError("stage 可选 planned、working 或 submitted。")
        receipt = item["review"]
        if receipt is not None:
            fields(receipt, "reviewer decision criterion checked sha256 inputs", "验收记录")
            if item["stage"] != "submitted":
                raise PlanError(f"{name} 请先交件，再填写验收记录。")
            handle(receipt["reviewer"], "reviewer")
            if receipt["reviewer"] == item["writer"]:
                raise PlanError(f"{name} 需要另一位复核员。")
            if receipt["decision"] not in ("pass", "revise"):
                raise PlanError("验收决定须明确填写 pass 或 revise。")
            for k in ("criterion", "checked"):
                sentence(receipt[k], k)
            digest(receipt["sha256"])
            if not isinstance(receipt["inputs"], dict) or set(receipt["inputs"]) != set(needs):
                raise PlanError(f"{name} 的验收记录须列全所用前置产物。")
            for sha in receipt["inputs"].values():
                digest(sha)
        tasks[name], paths[name], owners[key] = item, path, name
    for name, task in tasks.items():
        for dep in task["needs"]:
            if dep not in tasks:
                raise PlanError(f"{name} 引用了未登记的前置任务 {dep}。")
    try:
        order = list(TopologicalSorter({n: t["needs"] for n, t in tasks.items()}).static_order())
    except CycleError as exc:
        raise PlanError("任务依赖成环：" + " → ".join(exc.args[1])) from exc
    return tasks, paths, order


def assess(task, path, accepted):
    waiting = [name for name in task["needs"] if name not in accepted]
    if waiting:
        return "等前置", "待验收：" + "、".join(waiting), None
    if task["stage"] != "submitted":
        return ("可开工" if task["stage"] == "planned" else "制作中"), task["next"], None
    if not path.is_file():
        return "待补产物", "写者把当前产物放到约定位置后再请复核。", None
    raw = path.read_bytes()
    try:
        body = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "待补产物", "请将文稿另存为 UTF-8 文本后重新提交。", None
    if not any(c.isalnum() for c in body) or any(
        not c.isprintable() and c not in "\n\r\t" for c in body
    ):
        return "待补产物", "当前文件缺少可读文稿，请补齐内容再提交。", None
    review = task["review"]
    if review is None:
        return "待复核", "另一位复核员需打开当前产物，按验收条件核对并登记版本。", None
    sha = hashlib.sha256(raw).hexdigest()
    if sha != review["sha256"]:
        return "待复核", "产物版本已变，复核员须重新查看当前文件。", None
    if review["criterion"] != task["criterion"]:
        return "待复核", "验收条件已变，复核员须按当前条件重验。", None
    if review["inputs"] != {name: accepted[name] for name in task["needs"]}:
        return "待复核", "前置产物版本已变，须核对本任务使用的输入。", None
    if review["decision"] == "revise":
        return "需返工", f"{review['reviewer']} 提出修改：{review['checked']}", None
    return "已验收", f"{review['reviewer']} 已记录观察：{review['checked']}", sha


def plain(value):
    # Preserve free text as visible text in the Markdown report.
    return re.sub(r"([\\\x60*_{}\[\]()#+.!<>|&~-])", r"\\\1", value)


def board(plan, root):
    tasks, paths, order = validate_plan(plan, root)
    accepted, states = {}, {}
    for name in order:
        states[name] = assess(tasks[name], paths[name], accepted)
        if states[name][2]:
            accepted[name] = states[name][2]
    lines = ["# 任务分工看板", "", plain(plan["goal"]), ""]
    for name, task in tasks.items():
        state, action, _ = states[name]
        lines.extend([f"## {name} · {state}", "", f"- 写者：{task['writer']}",
                      f"- 产物：`{task['output']}`", f"- 验收条件：{plain(task['criterion'])}",
                      f"- 当前交代：{plain(action)}", ""])
    return "\n".join(lines), paths


def write_board(plan_file, target):
    plan = json.loads(plan_file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    content, paths = board(plan, plan_file.resolve().parent)
    destination = os.path.normcase(str(target.resolve())).casefold()
    for path in [plan_file, *paths.values()]:
        source = os.path.normcase(str(path.resolve())).casefold()
        if source == destination or source.startswith(destination + os.sep) or destination.startswith(source + os.sep):
            raise PlanError("看板请单独保存，避开计划文件和已认领的产物路径。")
    # Exclusive creation also handles two simultaneous requests for the same report.
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description="检查任务分工并生成离线 Markdown 看板。")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        write_board(args.plan, args.out)
    except FileExistsError:
        parser.exit(2, "看板已存在，请换一个新文件名重跑。\n")
    except (ValueError, UnicodeError) as exc:
        parser.exit(2, f"计划检查失败：{exc}\n")
    except OSError:
        parser.exit(2, "文件读写失败，请检查输入、输出目录和读取权限。\n")


if __name__ == "__main__":
    main()

"""Compare the ordinary files in two local folders without altering either folder."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def reject_link(metadata):
    attributes = getattr(metadata, "st_file_attributes", 0)
    if stat.S_ISLNK(metadata.st_mode) or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise ValueError("输入或报告位置含链接或重解析点。请选择本机普通目录。")


def checked_location(path):
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("请选择本机目录。")
    path = path.absolute()
    for component in reversed((path, *path.parents)):
        reject_link(component.lstat())
    return path.resolve(strict=True)


def fingerprint(metadata):
    # Windows path and handle APIs can report different meanings for ctime.
    change_time = 0 if os.name == "nt" else metadata.st_ctime_ns
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns,
            change_time, stat.S_IFMT(metadata.st_mode))


def snapshot(root):
    files = {}
    pending = [root]
    while pending:
        parent = pending.pop()
        reject_link(parent.lstat())
        for entry in parent.iterdir():
            metadata = entry.lstat()
            reject_link(metadata)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(entry)
            elif stat.S_ISREG(metadata.st_mode):
                files[entry.relative_to(root).as_posix()] = fingerprint(metadata)
            else:
                raise ValueError("发现特殊文件，请在只含普通文件的目录中重试。")
    return files


def hash_record(path, original):
    reject_link(path.lstat())
    with path.open("rb") as reader:
        if fingerprint(os.fstat(reader.fileno())) != original:
            raise ValueError("读取前文件已有变化，请等写入结束后重试。")
        digest = hashlib.file_digest(reader, "sha256").hexdigest()
        if fingerprint(os.fstat(reader.fileno())) != original:
            raise ValueError("读取期间文件已有变化，请等写入结束后重试。")
    return {"bytes": original[2], "sha256": digest}


def compare(source, copy):
    source_files = snapshot(source)
    copy_files = snapshot(copy)
    counts = dict.fromkeys(("same", "missing", "extra", "changed"), 0)
    rows = []
    for name in sorted(source_files.keys() | copy_files.keys()):
        a = hash_record(source / name, source_files[name]) if name in source_files else None
        b = hash_record(copy / name, copy_files[name]) if name in copy_files else None
        if a is None:
            status = "extra"
        elif b is None:
            status = "missing"
        else:
            status = "same" if a == b else "changed"
        counts[status] += 1
        rows.append({"path": name, "status": status, "source": a, "copy": b})
    if snapshot(source) != source_files or snapshot(copy) != copy_files:
        raise ValueError("前后目录清单发生变化，请等复制结束后重试。")
    if not rows:
        result = "empty"
    elif counts["same"] == len(rows):
        result = "match"
    else:
        result = "different"
    return {"algorithm": "SHA-256", "result": result, "summary": counts, "files": rows}


def run(source_path, copy_path, output):
    source = checked_location(source_path)
    copy = checked_location(copy_path)
    if not source.is_dir() or not copy.is_dir():
        raise ValueError("源和副本均须为已存在的目录。")
    if source.is_relative_to(copy) or copy.is_relative_to(source):
        raise ValueError("源和副本须为两个互不包含的目录。")
    if os.name == "nt":
        reserved = os.path.isreserved(output.name) if hasattr(os.path, "isreserved") else output.is_reserved()
        if reserved or ":" in output.name:
            raise ValueError("请使用普通的本机报告文件名。")
    report_path = checked_location(output.parent) / output.name
    if report_path.is_relative_to(source) or report_path.is_relative_to(copy):
        raise ValueError("报告须保存在两个待核目录以外。")
    if os.path.lexists(report_path):
        raise ValueError("报告位置已存在。请使用新文件名。")
    report = compare(source, copy)
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    with report_path.open("x", encoding="utf-8", newline="\n") as target:
        try:
            target.write(content)
            target.flush()
        except OSError:
            target.close()
            report_path.unlink()
            raise
    return 0 if report["result"] == "match" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--copy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        return run(args.source, args.copy, args.output)
    except ValueError as exc:
        print(f"无法完成校验：{exc}", file=sys.stderr)
    except OSError as exc:
        print(f"无法读写文件（错误号 {exc.errno}），请核对目录、权限和剩余空间。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

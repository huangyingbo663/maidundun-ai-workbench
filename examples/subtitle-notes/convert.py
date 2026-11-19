"""Convert a UTF-8 SRT file to a plain-text transcript with auditable cue times."""
import argparse
from pathlib import Path
import re
import sys


STAMP = r"[0-9]{2,}:[0-5][0-9]:[0-5][0-9],[0-9]{3}"
TIMING = re.compile(rf"[ \t]*({STAMP})[ \t]*-->[ \t]*({STAMP})[ \t]*")
NUMBER = re.compile(r"[0-9]+")


def milliseconds(stamp):
    hours, minutes, rest = stamp.split(":")
    seconds, millis = rest.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def convert(source):
    source = source.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    index = 0
    last_number = 0
    last_start = -1
    blocks = []
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        number = lines[index].strip()
        if not NUMBER.fullmatch(number) or int(number) <= last_number:
            raise ValueError(f"第 {index + 1} 行需要正整数段号，且须按原顺序递增")
        index += 1
        timing = TIMING.fullmatch(lines[index]) if index < len(lines) else None
        if not timing:
            raise ValueError(f"第 {index + 1} 行需要起止时间，例如 00:00:01,250 --> 00:00:03,000")
        start, end = timing.groups()
        start_ms = milliseconds(start)
        if milliseconds(end) <= start_ms:
            raise ValueError(f"第 {index + 1} 行的结束时间须晚于开始时间")
        if start_ms < last_start:
            raise ValueError(f"第 {index + 1} 行的开始时间早于上一段，需回查源文件")
        index += 1
        body_start = index
        while index < len(lines) and lines[index].strip():
            if NUMBER.fullmatch(lines[index].strip()) and index + 1 < len(lines) and TIMING.fullmatch(lines[index + 1]):
                raise ValueError(f"第 {index + 1} 行前缺少分隔两段字幕的空行")
            index += 1
        if index == body_start:
            raise ValueError(f"第 {body_start + 1} 行缺少字幕正文")
        blocks.append("\n".join([f"[{number} | {start} → {end}]", *lines[body_start:index]]))
        last_number = int(number)
        last_start = start_ms
    if not blocks:
        raise ValueError("文件中没有字幕段")
    return f"字幕核对稿（{len(blocks)} 段）\n\n" + "\n\n".join(blocks) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        notes = convert(args.input.read_text(encoding="utf-8-sig"))
        with args.output.open("x", encoding="utf-8", newline="\n") as out:
            out.write(notes)
    except FileExistsError:
        print("输出文件已存在，请另取文件名。", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print("输入无法按 UTF-8 解码，请把字幕副本另存为 UTF-8。", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"转换停止：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""离线筛选门店低库存、冷库有可调账存的商品，输出现场核数用的候选单。"""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path


QUANTITIES = {"store": "门店", "cold": "冷库", "reserved": "冷库预留", "in_transit": "在途"}
HEADER = {"threshold", "unit", "store_as_of", "cold_as_of", "items"}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 字段重复：{key}")
        result[key] = value
    return result


def label(value, field):
    if not isinstance(value, str) or not value.strip() or not value.strip().isprintable():
        raise ValueError(f"{field} 需要填一行有效文字")
    return value.strip()


def snapshot(value, field):
    text = label(value, field)
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field} 需要填写含时区的日期时间") from None
    if instant.utcoffset() is None:
        raise ValueError(f"{field} 需要填写时区，例如 +08:00")
    return instant


def classify(row, threshold):
    invalid = [title for key, title in QUANTITIES.items()
               if type(row.get(key)) is not int or row[key] < 0]
    if invalid:
        return "review", "请核对" + "、".join(invalid) + "的非负整件数"
    store, cold, reserved, transit = (row[key] for key in QUANTITIES)
    if reserved > cold:
        return "review", "冷库预留超过冷库账存，核对预留和出入库"
    if transit:
        return "review", f"在途数量 {transit}，核实到店与两地记账后重算"
    free = cold - reserved
    if store >= threshold:
        return "skip", f"门店 {store}，已达到筛选线"
    if free == 0:
        return "skip", f"门店 {store}，冷库账存 {cold}、预留 {reserved}，可调为 0"
    return "candidate", (f"门店 {store}，冷库账存 {cold}，预留 {reserved}，可调 {free}，"
                         f"补到筛选线的参考上限 {min(threshold - store, free)}")


def plan(data):
    if not isinstance(data, dict) or set(data) != HEADER:
        raise ValueError("核对顶层字段：threshold、unit、store_as_of、cold_as_of、items")
    threshold = data["threshold"]
    if type(threshold) is not int or threshold <= 0:
        raise ValueError("threshold 必须是正整数")
    unit = label(data["unit"], "unit")
    store_time = snapshot(data["store_as_of"], "store_as_of")
    cold_time = snapshot(data["cold_as_of"], "cold_as_of")
    if not isinstance(data["items"], list) or not data["items"]:
        raise ValueError("items 至少需要一行商品，请核对清单范围")

    groups = defaultdict(list)
    for index, row in enumerate(data["items"], 1):
        if not isinstance(row, dict) or row.keys() - ({"sku", "name"} | QUANTITIES.keys()):
            raise ValueError(f"第 {index} 行格式或字段名称不正确")
        sku = label(row.get("sku"), f"第 {index} 行 sku")
        name = label(row.get("name"), f"第 {index} 行 name")
        groups[sku].append((name, row))

    sections = {"candidate": [], "review": [], "skip": []}
    for sku in sorted(groups):
        entries = groups[sku]
        if len(entries) > 1:
            names = " / ".join(sorted({name for name, _ in entries}))
            sections["review"].append(f"{sku} ｜ {names} ｜ 同一 SKU 出现 {len(entries)} 行，先核对重复或批次")
            continue
        name, row = entries[0]
        status, reason = classify(row, threshold)
        sections[status].append(f"{sku} ｜ {name} ｜ {reason}")

    lines = ["冷库提货核数候选单", f"门店快照 {store_time.isoformat()}",
             f"冷库快照 {cold_time.isoformat()}", f"筛选线 {threshold}，统一单位 {unit}"]
    if store_time != cold_time:
        lines.append("两地快照时点不同，先核对时差内出入库。")
    lines.append("按账存筛选；提货前核实可售批次、现场余量、近期需求和门店空位。")
    for key, title in (("candidate", "账面候选"), ("review", "待核"), ("skip", "本次筛除")):
        rows = sections[key]
        lines.extend(["", f"{title}（{len(rows)} 款）", *(rows or ["无"])])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
        result = plan(data)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(result)
    except FileExistsError:
        parser.exit(1, "输出文件已存在，请换一个文件名。\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"未生成完整候选单：{exc}\n")


if __name__ == "__main__":
    main()

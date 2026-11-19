"""Reconcile paid voucher cohorts and dated redemption activity. Offline, one voucher per row."""
import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import sys


def unique_fields(pairs):
    record = {}
    for name, value in pairs:
        if name in record:
            raise ValueError("JSON 对象出现重名字段，请检查源文件")
        record[name] = value
    return record


def fields(obj, names, where):
    if not isinstance(obj, dict) or set(obj) != set(names.split()):
        raise ValueError(f"{where} 字段不匹配，请对照示例")


def identifier(value):
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ValueError("编号须填非空文字，首尾不得留空白")
    return value


def moment(value):
    if not isinstance(value, str):
        raise ValueError("时间须为 YYYY-MM-DD HH:MM:SS")
    stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if stamp.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise ValueError("时间须为 YYYY-MM-DD HH:MM:SS")
    return stamp


def reconcile(data):
    fields(data, "start end paid events", "顶层")
    start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    if start > end:
        raise ValueError("起日迟于止日")
    if not isinstance(data["paid"], list) or not isinstance(data["events"], list):
        raise ValueError("paid 和 events 都应为表格数组")
    paid = {}
    for row in data["paid"]:
        fields(row, "voucher order paid_at", "支付表")
        voucher = identifier(row["voucher"])
        identifier(row["order"])
        if voucher in paid:
            raise ValueError("支付表出现重复券编号，请确认每券一行")
        paid[voucher] = moment(row["paid_at"])
    transitions = {("unused", "redeem"): "used", ("used", "reverse"): "unused",
                   ("unused", "refund"): "refunded"}
    seen = {}
    for row in data["events"]:
        fields(row, "id voucher at action", "事件表")
        key = identifier(row["id"])
        voucher = identifier(row["voucher"])
        stamp = moment(row["at"])
        event = (stamp, voucher, row["action"])
        if key in seen and seen[key] != event:
            raise ValueError("同一事件编号的内容冲突，请核对原始记录")
        if voucher not in paid or stamp < paid[voucher]:
            raise ValueError("找不到对应支付记录，或事件早于支付")
        seen[key] = event
    states = dict.fromkeys(paid, "unused")
    at_end = states.copy()
    previous = {}
    activity = Counter()
    for stamp, voucher, action in sorted(seen.values(), key=lambda e: (e[0], e[1])):
        if previous.get(voucher) == stamp:
            raise ValueError("同券同秒出现不同事件，需核清先后顺序")
        previous[voucher] = stamp
        if (states[voucher], action) not in transitions:
            raise ValueError("券状态转换无效，请核对重复核销、撤销或退款")
        states[voucher] = transitions[states[voucher], action]
        if stamp.date() <= end:
            at_end[voucher] = states[voucher]
        if start <= stamp.date() <= end:
            activity[action] += 1
    cohort = {key for key, stamp in paid.items() if start <= stamp.date() <= end}
    counts = Counter(at_end[voucher] for voucher in cohort)
    effective = len(cohort) - counts["refunded"]
    def fraction(numerator, denominator):
        return f"{numerator}/{denominator}" if denominator else "无可计算分母"
    return {"统计期间": [start.isoformat(), end.isoformat()],
            "按事件发生日": {"核销笔数": activity["redeem"], "撤销核销笔数": activity["reverse"],
                       "净核销笔数": activity["redeem"] - activity["reverse"], "退款券数": activity["refund"]},
            "本期支付的券截至期末": {"支付成功券数": len(cohort), "已核销": counts["used"],
                           "已退款": counts["refunded"], "待使用": counts["unused"],
                           "支付券核销率": fraction(counts["used"], len(cohort)),
                           "有效券核销率": fraction(counts["used"], effective)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8-sig") as source:
            result = reconcile(json.load(source, object_pairs_hook=unique_fields))
        with args.output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (ValueError, OSError, TypeError) as exc:
        print(f"无法生成对账结果：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

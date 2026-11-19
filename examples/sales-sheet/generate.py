"""Build a public-facing, printable sales confirmation from an explicit field set."""
import argparse
from datetime import date
from html import escape
import json
from pathlib import Path
import re
import sys


def unique(pairs):
    obj = {}
    for name, value in pairs:
        if name in obj:
            raise ValueError("同一对象不能含重名字段")
        obj[name] = value
    return obj


def fields(obj, names):
    if not isinstance(obj, dict) or set(obj) != set(names.split()):
        raise ValueError("输入字段与示例不一致，请只保留对客表需要的字段")


def label(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("名称或规格须填写，且不能超过规定长度")
    if not value.isprintable():
        raise ValueError("名称与规格须为可打印的单行文字")
    return escape(value.strip())


def cents(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]{0,8})\.[0-9]{2}", value):
        raise ValueError("金额须为非负、两位小数的字符串，如 3.20")
    integer, decimal = value.split(".")
    return int(integer) * 100 + int(decimal)


def money(value):
    return f"¥{value // 100:,}.{value % 100:02d}"


def render(data):
    fields(data, "date revision items shipping")
    issued = data["date"]
    if date.fromisoformat(issued).isoformat() != issued:
        raise ValueError("日期格式须为 YYYY-MM-DD")
    revision = label(data["revision"], 32)
    if not isinstance(data["items"], list) or not data["items"]:
        raise ValueError("至少填写一个商品行")
    lines = []
    subtotal = 0
    for number, item in enumerate(data["items"], start=1):
        fields(item, "name spec quantity price")
        name, spec = label(item["name"], 80), label(item["spec"], 80)
        quantity = item["quantity"]
        if type(quantity) is not int or not 1 <= quantity <= 999999:
            raise ValueError("数量须为 1 到 999999 的整数")
        price = cents(item["price"])
        amount = quantity * price
        subtotal += amount
        lines.append(f"<tr><td>{number}</td><th scope='row'>{name}<small>{spec}</small></th>"
                     f"<td>{quantity}</td><td>{money(price)}</td><td>{money(amount)}</td></tr>")
    ship = data["shipping"]
    if isinstance(ship, dict) and ship.get("mode") == "fixed":
        fields(ship, "mode amount")
        fee = cents(ship["amount"])
        totals = f"<p>运费 <b>{money(fee)}</b></p><p class='total'>含运费合计 <b>{money(subtotal + fee)}</b></p>"
    else:
        fields(ship, "mode")
        if ship["mode"] != "separate":
            raise ValueError("运费方式须为 fixed 或 separate")
        totals = "<p class='total'>运费另算</p><p>待运费确认后再核对总金额。</p>"
    rows = "\n".join(lines)
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>销售确认单 · {revision}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1efe9;color:#263430;font:16px/1.55 system-ui,sans-serif}}
main{{width:min(100%,800px);margin:2rem auto;background:white;padding:clamp(16px,5vw,52px)}}
h1{{margin:0;color:#244b42;font-size:clamp(30px,7vw,50px)}}header p{{margin:.3em 0 1.7em}}
table{{border-collapse:collapse;width:100%;table-layout:fixed;font-variant-numeric:tabular-nums}}
th,td{{padding:.65em .25em;border-bottom:1px solid #cbcfc9;overflow-wrap:anywhere;text-align:right}}
th:first-child,td:first-child{{width:8%;text-align:left}}th:nth-child(2){{width:34%;text-align:left}}
thead{{color:#1f5345}}small{{display:block;font-size:.85em;font-weight:normal;color:#495751}}
footer{{margin:1.5rem 0 0 auto;max-width:340px}}footer p{{display:flex;justify-content:space-between;gap:1em;margin:.45em 0}}
.total{{color:#16493a;border-top:2px solid;padding-top:.55em;font-size:1.2em}}
@media(max-width:480px){{main{{margin:0 auto}}table{{font-size:13px}}}}
@page{{size:A4;margin:14mm}}@media print{{body,main{{background:white}}main{{margin:0;width:100%;padding:0}}thead{{display:table-header-group}}tr,footer{{break-inside:avoid}}}}
</style><main><header><h1>销售确认单</h1><p>{issued}　·　版本 {revision}　·　人民币</p></header>
<table aria-label="商品明细"><thead><tr><th>行</th><th>商品与规格</th><th>数量</th><th>单价</th><th>小计</th></tr></thead>
<tbody>{rows}</tbody></table><footer><p>货款小计 <b>{money(subtotal)}</b></p>{totals}</footer></main></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8-sig") as source:
            html = render(json.load(source, object_pairs_hook=unique))
        with args.output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(html)
    except (OSError, ValueError, TypeError) as exc:
        print(f"未生成新文件：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

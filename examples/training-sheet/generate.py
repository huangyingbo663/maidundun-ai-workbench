"""Build an offline, printable learner worksheet from a local UTF-8 JSON file."""
import argparse
from html import escape
import json
from pathlib import Path
import sys


def unique_fields(pairs):
    record = {}
    for name, value in pairs:
        if name in record:
            raise ValueError(f"重复的 JSON 字段：{name}")
        record[name] = value
    return record


def exact_fields(record, expected, section):
    if not isinstance(record, dict) or set(record) != set(expected):
        raise ValueError(f"{section} 字段应为 {', '.join(expected)}")


def plain(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 需要非空文本")
    value = value.strip()
    if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
        raise ValueError(f"{label} 含无效控制字符")
    return escape(value, quote=True)


def items(values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} 至少需要一项")
    return "\n".join(f"<li>{plain(text, label)}</li>" for text in values)


STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #25352c; background: #f0f2ec; }
* { box-sizing: border-box; }
body { margin: 0; line-height: 1.65; }
main { margin: auto; max-width: 50rem; padding: 1.4rem; }
article { background: white; margin: 0 0 1.2rem; padding: clamp(1.3rem,5vw,3.2rem); border-top: .4rem solid #28664d; }
.review { border-color: #9a5b25; }
header { border-bottom: 1px solid #b7c5b8; padding-bottom: .8rem; }
header p { margin: 0; color: #435b4b; }
h1, h2, p, li { overflow-wrap: anywhere; white-space: pre-wrap; }
h1 { line-height: 1.2; font-size: clamp(1.7rem,5vw,2.35rem); margin: .35rem 0; }
h2 { font-size: 1.13rem; margin: 1.3rem 0 .25rem; color: #295d46; }
.review h2 { color: #76451e; }
p, ul, ol { margin: .25rem 0; }
ul, ol { padding-left: 1.5rem; }
li { margin: .2rem 0; padding-left: .1rem; }
li::marker { font-weight: 650; }
.callout { padding: .65rem .9rem; border-left: .2rem solid #8ba492; background: #f3f6ef; }
.record { border: 1px solid #adb8ad; padding: .7rem 1rem; margin-top: 1.1rem; min-height: 5rem; }
@page { size: A4; margin: 15mm 17mm; }
@media print {
  :root, body { color: #111; background: white; font-size: 10.5pt; }
  main, article { max-width: none; margin: 0; padding: 0; }
  article { border: none; }
  article + article { break-before: page; }
  header, h2 { break-after: avoid; }
  h1 { font-size: 21pt; }
  h2 { font-size: 13pt; margin-top: 10pt; }
  p, li { orphans: 2; widows: 2; }
  .record { break-inside: avoid; }
}
"""


def render(data, audience_mode="full"):
    fields = ("title", "version", "audience", "objective", "materials", "steps",
              "submission", "prompt", "checks", "transfer")
    exact_fields(data, fields, "根对象")
    title, version, audience, objective, submission, prompt = (
        plain(data[key], key) for key in ("title", "version", "audience", "objective", "submission", "prompt"))
    materials = items(data["materials"], "materials")
    steps = items(data["steps"], "steps")
    checks = items(data["checks"], "checks")
    change = data["transfer"]
    exact_fields(change, ("variation", "expected"), "transfer")
    variation = plain(change["variation"], "transfer.variation")
    expected = plain(change["expected"], "transfer.expected")
    review_sheet = ""
    if audience_mode == "full":
        review_sheet = f"""<article class="review" aria-labelledby="review-title">
<header><p>复核人用 · {version}</p><h1 id="review-title">独立验收</h1><p>{title}</p></header>
<h2>核对提交件</h2><ol>{checks}</ol>
<h2>换一组条件</h2><p>{variation}</p>
<h2>对照结果</h2><p class="callout">{expected}</p>
<section class="record"><h2>复核记录</h2><p>记下提交件版本、通过的项目和需要修改的原句。修订后用新版本复查。</p></section>
</article>"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {version}</title>
<style>{STYLE}</style>
</head>
<body><main>
<article aria-labelledby="learner-title">
<header><p>学员任务单 · {version}</p><h1 id="learner-title">{title}</h1><p>{audience}</p></header>
<h2>完成目标</h2><p>{objective}</p>
<h2>手边材料</h2><ul>{materials}</ul>
<h2>动手练习</h2><ol>{steps}</ol>
<h2>交付物</h2><p class="callout">{submission}</p>
<h2>可复制的练习提示词</h2><p>{prompt}</p>
</article>
{review_sheet}
</main></body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audience", choices=("full", "learner"), default="full",
                        help="learner 仅导出练习；full 同时导出复核页（默认）")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_fields)
        html = render(data, args.audience).encode("utf-8")
        with args.output.open("xb") as target:
            target.write(html)
    except (ValueError, OSError, RecursionError) as exc:
        print(f"未生成任务单：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

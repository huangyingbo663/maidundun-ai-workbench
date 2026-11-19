#!/usr/bin/env python3
"""Offline JSON -> printable shot cards. Python 3.10+, standard library only.

SPDX-License-Identifier: MIT
Copyright (c) 2026 麦囤囤·AI工坊
"""
import argparse
from decimal import Decimal
from html import escape
import json
import math
from pathlib import Path, PureWindowsPath
import re
import sys


class InputError(ValueError):
    """An actionable input or output-path error."""


def fields(value, required, optional, location):
    if not isinstance(value, dict):
        raise InputError(f"{location}: expected an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing:
        raise InputError(f"{location}: missing required field(s): {', '.join(sorted(missing))}")
    if extra:
        raise InputError(f"{location}: unknown field(s): {', '.join(sorted(extra))}")


def text(value, location, limit=300):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{location}: expected non-empty text")
    if len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise InputError(f"{location}: text must be <= {limit} characters without control codes")
    return value.strip()


def identifier(value, location):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
        raise InputError(f"{location}: use 1-32 letters, digits, hyphens or underscores")
    return value


def array(value, location, low, high):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise InputError(f"{location}: expected {low}-{high} items")
    return value


def validate(data):
    fields(data, ('version', 'title', 'purpose', 'product', 'shots'), ('reference_summary',), 'input')
    if type(data['version']) is not int or data['version'] != 1:
        raise InputError('version: expected integer 1')
    title = text(data['title'], 'title', 80)
    purpose = text(data['purpose'], 'purpose')
    reference = text(data['reference_summary'], 'reference_summary', 500) if 'reference_summary' in data else ''
    product = data['product']
    fields(product, ('name', 'approved_facts'), (), 'product')
    name = text(product['name'], 'product.name', 80)
    facts = {}
    for i, fact in enumerate(array(product['approved_facts'], 'product.approved_facts', 1, 20)):
        where = f'product.approved_facts[{i}]'
        fields(fact, ('id', 'text'), (), where)
        key = identifier(fact['id'], where + '.id')
        if key in facts:
            raise InputError(where + ': duplicate fact id')
        facts[key] = text(fact['text'], where + '.text', 160)
    shots, ids = [], set()
    for i, shot in enumerate(array(data['shots'], 'shots', 1, 40)):
        where = f'shots[{i}]'
        fields(shot, ('id', 'duration_seconds', 'role', 'frame', 'action', 'audio', 'fact_ids', 'capture_check'), ('shooting_tip',), where)
        key = identifier(shot['id'], where + '.id')
        if key in ids:
            raise InputError(where + ': duplicate shot id')
        ids.add(key)
        duration = shot['duration_seconds']
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0.1 <= duration <= 120:
            raise InputError(where + '.duration_seconds: expected a finite number from 0.1 to 120')
        duration = Decimal(str(duration))
        if duration != duration.quantize(Decimal('0.1')):
            raise InputError(where + '.duration_seconds: at most one decimal place')
        refs = array(shot['fact_ids'], where + '.fact_ids', 0, 20)
        if any(not isinstance(ref, str) or ref not in facts for ref in refs):
            raise InputError(where + '.fact_ids: unknown fact id')
        if len(refs) != len(set(refs)):
            raise InputError(where + '.fact_ids: duplicate fact id')
        row = {'id': key, 'duration': duration, 'facts': [facts[ref] for ref in refs]}
        for field in ('role', 'frame', 'action', 'audio', 'capture_check'):
            row[field] = text(shot[field], where + '.' + field)
        row['shooting_tip'] = text(shot['shooting_tip'], where + '.shooting_tip') if 'shooting_tip' in shot else ''
        shots.append(row)
    return {'title': title, 'purpose': purpose, 'name': name, 'reference': reference, 'facts': facts, 'shots': shots}


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f'JSON: duplicate key {key!r}')
        result[key] = value
    return result


def load_input(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise InputError('input: maximum JSON size is 1 MiB')
    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=no_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError(f'input: invalid UTF-8 JSON ({exc})') from exc
    return validate(data)


def seconds(value):
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


CSS = """
:root{color-scheme:light;--ink:#193d36;--muted:#53685e;--paper:#f7f5ec;--line:#d5ded4;--accent:#b84f24}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:auto;padding:32px 24px 48px}.hero{background:var(--ink);color:#fff;border-radius:20px;padding:30px 32px}
.eyebrow{font-size:13px;letter-spacing:.12em;margin:0 0 12px;color:#c7dfcf}h1{font-size:clamp(26px,4vw,40px);line-height:1.25;margin:0 0 18px}h2{font-size:21px;margin:0}p{margin:8px 0}
.summary{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}.pill{border:1px solid #8da89b;border-radius:100px;padding:5px 14px;font-size:14px}
.toolbar{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:24px 0;color:var(--muted);font-size:14px}button{border:0;border-radius:9px;padding:10px 18px;background:var(--ink);color:white;font:inherit;cursor:pointer}
.context{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px 24px;margin:20px 0}.context ul{padding-left:22px;margin:10px 0}.reference{color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px;break-inside:avoid;overflow-wrap:anywhere}
.card-head{display:flex;align-items:center;gap:14px;margin-bottom:17px}.number{background:#f8e6d7;color:var(--accent);font-size:25px;font-weight:750;width:50px;height:50px;display:grid;place-items:center;border-radius:12px;flex-shrink:0}
.timing{color:var(--muted);font-size:13px;margin:1px 0}.row{display:grid;grid-template-columns:68px 1fr;gap:12px;margin:12px 0}.label{color:var(--muted);font-size:13px;padding-top:2px}.value{white-space:pre-wrap}.fact{background:#edf4ed;border-radius:8px;padding:10px 12px;margin-top:14px}.fact strong{font-size:13px}.fact ul{padding-left:19px;margin:5px 0}
.check{border-top:1px dashed var(--line);padding-top:12px;margin-top:15px}.check b{font-size:13px}.check p{margin-bottom:0}.tick{display:inline-block;width:13px;height:13px;border:1px solid #5f7365;margin-right:7px;vertical-align:-1px}.notes{margin-top:14px;color:var(--muted);font-size:13px}.writing-line{height:24px;border-bottom:1px solid var(--line)}footer{margin-top:24px;font-size:13px;color:var(--muted)}
@media(max-width:720px){main{padding:16px 12px 30px}.hero{padding:24px 21px}.grid{grid-template-columns:1fr}.toolbar{align-items:flex-start}.context{padding:18px}.card{padding:19px}}
@page{size:A4;margin:12mm}@media print{body{background:white;font-size:11pt}main{padding:0;max-width:none}.hero{background:white;color:#111;border:1px solid #777;border-radius:0;padding:12px 16px}.eyebrow{color:#333}.hero h1{font-size:23pt}.summary{margin-top:10px}.pill{color:#222;border-color:#777}.toolbar{display:none}.context{padding:12px 16px;margin:12px 0}.grid{gap:10px}.card{border-radius:0;padding:13px}.number{background:white;border:1px solid #777;color:#111;width:36px;height:36px;font-size:18pt}.card-head{gap:10px}.card h2{font-size:14pt}.row{grid-template-columns:48px 1fr;gap:8px;margin:8px 0}.label,.timing,.notes,.check b,.fact strong{font-size:9pt}.fact{background:white;border:1px solid #aaa}.writing-line{height:18px}footer{font-size:9pt}}
"""


def render(plan):
    e = escape
    total = sum((shot['duration'] for shot in plan['shots']), Decimal(0))
    cards, cursor = [], Decimal(0)
    for number, shot in enumerate(plan['shots'], 1):
        end = cursor + shot['duration']
        rows = ''.join(f'<div class="row"><span class="label">{label}</span><div class="value">{e(shot[field])}</div></div>' for label, field in [('画面', 'frame'), ('动作', 'action'), ('声音', 'audio')])
        facts = '<ul>' + ''.join(f'<li>{e(fact)}</li>' for fact in shot['facts']) + '</ul>' if shot['facts'] else '<p>本镜不增加产品事实。</p>'
        tip = f'<p class="notes">拍摄提示：{e(shot["shooting_tip"])}</p>' if shot['shooting_tip'] else ''
        cards.append(f'''<article class="card" data-shot-id="{e(shot['id'])}">
<div class="card-head"><div class="number">{number:02d}</div><div><p class="timing">{seconds(cursor)}–{seconds(end)} 秒 · 本镜 {seconds(shot['duration'])} 秒</p><h2>{e(shot['role'])}</h2></div></div>
{rows}<div class="fact"><strong>可引用的已核信息</strong>{facts}</div>{tip}
<div class="check"><b><span class="tick"></span>拍后确认</b><p>{e(shot['capture_check'])}</p></div>
<div class="notes">素材编号 / 重拍备注<div class="writing-line"></div></div></article>''')
        cursor = end
    reference = f'<p class="reference">结构依据：{e(plan["reference"])}</p>' if plan['reference'] else ''
    facts = ''.join(f'<li>{e(key)}：{e(value)}</li>' for key, value in plan['facts'].items())
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(plan['title'])} · 拍摄卡</title><style>{CSS}</style></head>
<body><main><header class="hero"><p class="eyebrow">麦囤囤 · AI工坊 / 实拍拍摄卡</p><h1>{e(plan['title'])}</h1><p>{e(plan['purpose'])}</p><div class="summary"><span class="pill">{e(plan['name'])}</span><span class="pill">{len(plan['shots'])} 镜 · 计划 {seconds(total)} 秒</span><span class="pill">拍前核事实 · 拍后看完整动作</span></div></header>
<div class="toolbar"><span>屏幕阅读或浏览器打印；时长是剪辑计划，不是已拍成片。</span><button type="button" onclick="window.print()">打印 / 保存 PDF</button></div>
<section class="context"><h2>本次拍摄依据</h2>{reference}<ul>{facts}</ul><p class="reference">请由操作者确认这些事实适用于本次真实产品。工具只校验字段与引用，不替代产品核实。</p></section>
<section class="grid">{''.join(cards)}</section><footer>本页离线生成，无账号、无网络素材。按卡拍摄后，逐镜检查动作、商品与声音，再进入剪辑。</footer></main></body></html>
'''


def output_path(value, root):
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).drive or '..' in path.parts or '\\' in value:
        raise InputError('output: use a relative path inside the current directory; no traversal or backslashes')
    for part in path.parts:
        stem = part.split('.')[0].upper()
        if (not part or part.endswith((' ', '.')) or any(c in part for c in ':<>|?*')
                or stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(COM|LPT)[1-9]', stem)):
            raise InputError('output: unsafe or reserved path component')
    if path.suffix.lower() != '.html':
        raise InputError('output: filename must end in .html')
    root = root.resolve()
    target = root / path
    try:
        target.resolve().relative_to(root)
    except ValueError as exc:
        raise InputError('output: resolved path leaves the current directory') from exc
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise InputError('output: symbolic links and junctions are not accepted')
    if target.exists():
        raise InputError('output: file already exists; choose a new filename to preserve it')
    if not target.parent.is_dir():
        raise InputError('output: parent directory must already exist')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create offline printable shot cards from JSON; never overwrite outputs.')
    parser.add_argument('--input', required=True, help='UTF-8 JSON input; see demo.json')
    parser.add_argument('--output', required=True, help='new .html file relative to the current directory')
    args = parser.parse_args(argv)
    try:
        plan = load_input(args.input)
        target = output_path(args.output, Path.cwd())
        content = render(plan)
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
        print(f'generated={Path(args.output).as_posix()} shots={len(plan["shots"])}')
        return 0
    except (InputError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

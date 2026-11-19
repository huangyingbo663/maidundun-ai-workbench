# 谁可以开工

把任务交给几个人时，先约定谁写哪个文件、要等谁交件、怎样才算通过。这个工具把约定变成一张可读的看板。示例是一家虚构门店的周末阅读活动，顾客需要一张领取、体验和归还的指引卡。

## 先生成一张看板

下载并解压整个仓库，在含有仓库首页 README 的文件夹打开终端。准备 Python 3.12 或以上版本。Windows 如果用 `py` 启动 Python，可将命令开头的 `python` 改成 `py`。

```
python -B -X utf8 examples/work-brief/plan.py examples/work-brief/sample.json --out work-board.md
```

用文本编辑器打开新生成的 `work-board.md`，与[预期看板](expected.md)对照。对应的[计划](sample.json)和[活动说明](materials/event-facts.md)也能在浏览器直接阅读。

| 任务 | 看板状态 | 拿到看板后做什么 |
| --- | --- | --- |
| facts · 活动说明 | 已验收 | 复核员已看过三步，打开文件可核对其观察。 |
| copy · 三行指引 | 可开工 | 写者 writer 打开活动说明，为第一次来的顾客写三行话。 |
| layout · 排版 | 等前置 | 先等 copy 的当前版本通过复核。 |

## 实际接力一次

1. 从仓库根目录运行下面三条命令。第一条把派工材料复制到新的 `practice-board` 文件夹。第二条检查随仓附带的交接材料。第三条把其中的文案按原字节复制到派工表给 writer 预留的位置。

   ```
   python -c "import shutil; shutil.copytree('examples/work-brief','practice-board')"
   python -B -X utf8 examples/handoff-check/check_handoff.py --input examples/handoff-check/sample.json --output handoff-first.json
   python -c "from pathlib import Path; src=Path('examples/handoff-check/artifacts/guide.md'); dst=Path('practice-board/materials/card-copy.md'); f=dst.open('xb'); f.write(src.read_bytes()); f.close()"
   ```

2. 打开 `handoff-first.json`、[文案原件](../handoff-check/artifacts/guide.md)和[原始复核记录](../handoff-check/reviews/guide.json)。逐条对照自己副本里的 `materials/event-facts.md`。查原复核员与写者、三步顺序、地点及对应版本。下面的命令依次显示文案摘要和活动说明摘要。SHA-256 是文件内容的指纹，换行也会影响结果。

   ```
   python -c "from pathlib import Path; from hashlib import sha256; print(sha256(Path('practice-board/materials/card-copy.md').read_bytes()).hexdigest()); print(sha256(Path('practice-board/materials/event-facts.md').read_bytes()).hexdigest())"
   ```

3. 用文本编辑器打开 `practice-board/sample.json`，找到 `"id": "copy"`。在这项里把 `"stage": "planned"` 改为 `"stage": "submitted"`。如果原复核记录对应当前文案及判断条件，且逐条对照过的活动说明与其已验收摘要相符，把相邻的 `"review": null` 替换成下面整段。第一项摘要是文案，`inputs.facts` 是写这版文案所依据的活动说明。练习沿用原记录中 checker 的观察。实际项目应由另一位复核员逐项查看当前版本，留下自己的观察和结论。

   ```json
   "review": {
     "reviewer": "checker",
     "decision": "pass",
     "criterion": "逐条核对领取地点、体验位置和归还地点，读者能按顺序走完。",
     "checked": "逐行读过三步。第一步到咨询台领取，第二步到入口旁的阅读区，第三步回咨询台归还；地点和顺序均清楚。",
     "sha256": "d71f25ea9e236a5e0acbea8ff41bd6d8813a57b363350522749f2aa8242fda4e",
     "inputs": {
       "facts": "c7ae2af91e57e207b9a2625ea6f867d3f793361e7e88c27283b98cda12cd1271"
     }
   }
   ```

4. 运行 `python -B -X utf8 practice-board/plan.py practice-board/sample.json --out work-board-v2.md`。打开结果，copy 应为「已验收」，layout 应为「可开工」。排版人员现在能接任务；首个动作是向场地协调者取得展示架可用宽高，记下数值、单位和来源，再实际出稿。在交接练习中，这项尺寸仍待提供。现场挂好后由现场人员另行查看入口能否看清卡片。
5. 做一次反向检查。在副本的 `card-copy.md` 末尾加一句话，再以新的输出名运行。copy 应变为「待复核」，layout 应回到「等前置」。如果原文确需更改，复核员应重读后记录新版观察和摘要。

## 给自己的任务填写计划

沿用 `sample.json` 的结构。一个任务对应一位写者、一份产物和一个可观察的验收条件。给一人安排多份产物时，用多行任务、同一写者编号。负责人保管计划，写者只写认领的产物；复核员把观察交给负责人登记。看板适用于在约定目录内协作的小组，文件写权限和人员身份由团队管理。

| 字段 | 怎样填写 |
| --- | --- |
| goal | 最终读者能拿到什么，能做什么。 |
| id / writer | 稳定的任务编号与写者编号。用小写英文字母开头，可加数字和短横线。独立复核员使用自己的编号。 |
| output | 相对于计划文件的路径，以 `materials/` 开头。使用普通 UTF-8 的 `.md` 或 `.txt` 文稿。 |
| needs | 等待的前置任务编号。没有填空列表 `[]`，两条依赖用 `["facts", "copy"]`。 |
| criterion / next | 复核员能在产物里看到什么；写者接下来亲手做什么。 |
| stage | `planned` 待开工、`working` 已开工、`submitted` 已交件。正在工作时记上 `working`，便于接手者联系原写者。 |
| review | 等待复核时填 `null`。复核员给出 `pass` 或 `revise`，写观察、验收条件原文、本件摘要和每个前置输入的摘要。遇到需修改的内容，`checked` 写具体问题。 |

可以把下面这段发给协作者，再把填写结果放回计划。

> 请把这次门店活动拆成可以交付的文稿。每项写清唯一写者、文件名、前置任务、验收员能看见什么，以及接到任务后的第一个动作。需要实测的条件写出提供者和恢复动作。没有交件的任务保留待办，没有独立观察的文稿保留待复核。

## 看板提示怎样处理

- 「待补产物」时先找规定位置的文件，确认是可读 UTF-8 文稿，并有实际文字。
- 「待复核」时打开最新版，与任务条件逐项比对。产物、验收条件或已采纳的前置材料变更后，需要复核当前版本。
- 「需返工」时由原写者阅读复核员的观察，另存修改稿、核对当前使用的版本，再请复核员阅读。
- 同一文件重复认领、一个路径既作文件又作目录、依赖环或未知编号会终止本次生成。看提示先修计划，输出文件使用新名字。工具按约定的路径和复核记录核对，人眼负责判断文字是否与事实相符。
- 工具只读计划及其中声明的本地文稿，输出一个新看板。它不调用模型，也不代发任务。换人时交付计划、文稿、复核记录，再从新会话重建看板。

维护者在仓库根目录运行 `python -B -X utf8 -m unittest discover -s examples/work-brief -p "test_*.py"`。更新练习后同时核对预期看板、配套文案和接力演练中的两个摘要。

[查看验收与换人接续](../handoff-check/README.md)

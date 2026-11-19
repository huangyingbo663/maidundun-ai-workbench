# 把逐镜计划变成可打印拍摄卡

不用账号、API、模型或第三方包。准备 Python 3.10 或更新版本，在下载的项目根目录运行：

```bash
python examples/shot-cards/generate.py --input examples/shot-cards/demo.json --output shot-cards-demo.html
```

成功时会显示 `generated=shot-cards-demo.html shots=4`。双击生成的 HTML，在浏览器中阅读，或点“打印 / 保存 PDF”。[随附成品 demo.html](demo.html) 是同一输入实际生成的文件；GitHub 文件页可能显示源码，下载后再用浏览器打开。

示例商品和文字是原创演示，不是门店在售资料。工具只生成拍摄计划；不拍摄、不剪辑、不联网、不判断商品事实是否真实。

## 不会写 JSON，可以把这段给 AI

> 请读取这个项目的 `skills/reference-to-shot-cards/SKILL.md`。我要拍【产品】，现已核实的信息是【外观、规格或动作事实】，现有场景和工具是【补充】。请先把参考中值得保留的镜头作用写清楚，再换成我的真实动作，按 `examples/shot-cards/demo.json` 的格式生成新输入。不要编价格、销量或健康承诺。调用本地工具，输出一个新文件名，给我可浏览的拍摄卡；关键事实缺失就明确列出来。

没有参考也能用：明确说“按原创结构做”，不要把原创构思写成已观察到的参考内容。

## 换成自己的产品

复制 `demo.json` 为 `my-product.json`，再修改标题、目标、产品和各镜头。先维护 `product.approved_facts`，然后让每镜用 `fact_ids` 引用对应事实；工具会把事实原文放到卡片上。改产品后仍须检查动作、声音与标题是否适合新产品，它不会自动改写自由文本。

```bash
python examples/shot-cards/generate.py --input my-product.json --output my-product-v1.html
```

| 字段 | 填什么 |
|---|---|
| `version` | 整数 `1` |
| `title` / `purpose` | 本条题目 / 想让观众看明白什么 |
| `product.name` | 本次真实产品名称 |
| `product.approved_facts` | 1–20条已核事实，每条含唯一 `id` 和 `text` |
| `reference_summary` | 可选，观察到的参考结构或明确标为原创的结构 |
| `shots` | 1–40个镜头，按拍摄计划顺序排列 |
| `id` / `duration_seconds` | 镜头唯一编号 / 计划秒数，0.1–120，最多一位小数 |
| `role` | 这一镜为什么存在，例如交代商品、揭示细节、完成收尾 |
| `frame` / `action` | 画面范围和机位 / 完整动作怎么做 |
| `audio` | 现场声、口播或后期声音的计划；未知项明确待定 |
| `fact_ids` | 本镜引用的事实编号；没有新增信息可用空数组 |
| `capture_check` | 拍完具体看什么，例如焦点、完整动作、数量和产品一致 |
| `shooting_tip` | 可选的操作提示 |

ID使用字母、数字、连字符或下划线。JSON采用UTF-8，最大1MiB；未知字段会报错，避免字段拼错却被忽略。

## 出错时怎么处理

| 提示 | 处理 |
|---|---|
| `missing required field` | 补上错误中指出的字段，不填空字符串凑数 |
| `unknown fact id` | 让 `fact_ids` 与本产品的事实编号一致 |
| `file already exists` | 旧输出被保留，改成 `my-product-v2.html` 等新名字 |
| `parent directory must already exist` | 先建子目录，或直接输出到当前目录 |
| `relative path` / `resolved path leaves` | 输出使用当前工作目录内的相对路径；不接受 `..`、绝对路径或链接目录 |

退出码：成功为 `0`，输入/路径/文件错误为 `2`。输出必须是 `.html`；子目录请用 `/`，例如 `exports/cards-v1.html`。工具拒绝覆盖旧文件与符号链接，不充当针对并发恶意文件系统操作的安全沙箱。

## 维护与验证

```bash
python -B -m unittest discover -s examples/shot-cards/tests -v
```

测试把脚本复制到独立临时目录，使用 Python `-I -S` 运行，覆盖换产品与时长、缺字段、事实引用、HTML转义、旧输出保留、路径越界及确定性输出。不能创建符号链接的系统会明确跳过那一项。临时目录建立在测试目录内，结束后清理。

输出是UTF-8、LF换行，无时间戳、宿主路径、外部字体或网络素材。同一输入的预期产物为 `demo.html`；维护者改版式时，应审阅新结果后更新这个基准。打印分页还受浏览器、字体和纸张设置影响，先看打印预览再出纸。

代码及原创示例数据：MIT。本文档：CC BY 4.0，署名“麦囤囤·AI工坊”。第三方参考原件不包含在本示例中。

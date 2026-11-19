# 怎样检查和维护这个项目

每次更新后，先确认“链接能打开、工具能运行、结果没变坏”。每月再把备份恢复到一个新目录，检查恢复后还能用。

不熟悉命令时，把下面的话连同项目目录交给 AI：

> 请按本项目维护说明运行检查，把报告保存到新的目录。失败时告诉我哪个文件、哪一步出了问题，修好后再检查。不要跳过失败项，不要为了通过检查随意修改预期结果，不调用收费服务。

## 本机检查

需要 Python 3.12 或更新版本；月度恢复还需要 Git。维护工具只用标准库，不要求账号、密钥或 GPU。打开项目根目录中的终端：

```sh
python -B -X utf8 tools/maintain.py weekly --root . --out ../weekly-check-v1
```

结果保存在新目录 `weekly-check-v1`。打开 `report.md` 看结论，`report.json` 供工具读取。检查会核对公开文件清单、文件内容、本地链接，并真实运行[镜头卡示例](../examples/shot-cards/README.md)，同时复算门店提货与团购核销。设计交付的两项工具会重新生成培训任务单和销售确认单。办公自动化工具逐文件比较两份演示目录，并将 SRT 字幕整理成保留时间的核对稿。协作工具重新生成分工看板和接班结果，核对写者、依赖、受审文件版本和待办。九个示例均与随包的预期文件比较。执行环境在报告目录内，不覆盖项目中的示例。

退出码 `0` 表示本次本地检查通过，`1` 表示检查失败，`2` 表示路径或运行参数不合适。输出目录已存在时，请用 v2、v3 等新名字，保留旧报告。

请检查干净的公开项目副本。自己运行示例后新增的 HTML、输入或缓存不在公开登记表中时，会提示“未登记文件”；先将自己的成果另存到项目外，再用干净副本检查。不要为了消除提示删除自己的材料，也不要把私密文件加入公开登记表。

## 每月恢复一次

在干净且已经提交的本地 Git 仓库根目录执行：

```sh
python -B -X utf8 tools/maintain.py monthly --root . --out ../monthly-check-v1
```

它先完成普通检查，再生成公开包 ZIP 和 Git bundle，在新目录恢复、对比分支/标签和提交，并重新运行样例。若下载的是不含 Git 历史的 ZIP，可运行周检；月检会明确报告无法完成 Git 恢复。

生成的文件保存在本机报告目录，不会自动上传。请按自己的备份安排保留到另一可靠位置。这个流程没有备份 GitHub Issues、附件、Wiki、LFS 对象或其他平台数据；实际用了这些内容时，要另行导出并验证恢复。

## GitHub 上怎样运行

工作流文件为 `.github/workflows/maintenance.yml`，包含：

- 提交到 main 和提交 PR 时检查。
- 每周二北京时间 10:17 检查。
- 每月 1 日北京时间 10:43 检查并恢复。
- 在 Actions 页面选择 **Public package maintenance → Run workflow**，手动选择 weekly 或 monthly。

运行页面显示结果和摘要；详细 JSON 也写入日志。将 `offline-checks` 配为分支规则中的必需检查后，失败结果才能阻止合并。仓库默认分支若改名，维护者需同步修改工作流的 push 分支条件。

工作流默认只读仓库。只有维护者主动设置仓库变量 `MAINTENANCE_ISSUES=enabled` 后，定时或手动检查失败才会由单独的最小权限 job 创建一条问题记录；已有同标题未关闭问题时不重复创建。普通 PR 不触发这个写入 job。默认不发送外部通知、不自动修复或合并，不调用付费模型。

GitHub 定时任务可能延迟或停用，所以维护者还要定期查看最近一次真实成功时间。手动运行通过不能证明定时已经触发。依赖更新模板仅登记本仓库使用的 GitHub Actions；漏洞告警及所用依赖需在仓库 Security 设置和实际告警中确认。[GitHub 定时说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

Actions 中生成的 ZIP 和 bundle 是当次临时恢复演练，本工作流没有自动保存这些备份。日志和摘要也受 GitHub 保留设置影响，不能当永久资产备份。[备份说明](https://docs.github.com/en/repositories/archiving-a-github-repository/backing-up-a-repository)

## 更新项目后，怎样更新检查标准

`public-export-receipt.json` 是公开文件登记表，`maintenance.json` 声明必需文件和关键样例。登记表不会自动批准新内容；修改代码、文档或示例后，先审查差异、许可和实际结果，再更新登记。

1. 新增或删除文件时，由维护者调整登记表的文件条目，保留用途和许可依据。不能把私密文件或运行报告加入公开清单。
2. 从项目根目录运行下列命令。它只在新目录生成候选，不覆盖当前登记表。

```sh
python -B -X utf8 tools/maintain.py register --root . --out ../registration-v2
```

3. 对比 `registration-v2/receipt-candidate.json` 与旧登记表。候选状态是 `needs_review`，检查工具会拒绝把它当已批准回执。审查完成后，维护者才把状态改回 `exported` 并采用为根目录的 `public-export-receipt.json`，保留 schema_version、network_used 和原许可说明，再重跑检查。
4. 若镜头卡输出是有意改变，先打开并检查新的 HTML，再由示例维护者更新 `examples/shot-cards/demo.html` 基准。不能只改预期值来掩盖程序错误。

登记表保留原字节 `sha256`；UTF-8 文本还登记 `sha256_lf`，将 CRLF/CR 统一为 LF 后计算。存在显式 `sha256_lf` 时按它验证文本，二进制仍逐字节验证；旧回执没有该字段时沿用原 SHA。这样换操作系统不会因正常换行变化误报，实际文字或代码变化仍然失败。`.gitattributes` 同时声明 Git 文本换行为 LF。

## 检查的边界

本地检查证明登记文件、常规 Markdown/HTML 链接及所配置样例的确定性结果。它不会替代内容审美、事实和版权审查，也不执行外部链接抓取、收费模型、平台发布或远端恢复。样例脚本经过登记仍不是安全沙箱；维护者只应加入已审查的离线短任务。

工作流使用固定完整 Action SHA，默认最小权限。维护者更新 Action、Python 或示例依赖时，应先核官方版本，再做同样检查并保留变更记录。[安全使用说明](https://docs.github.com/en/actions/reference/security/secure-use)

本文档采用 CC BY 4.0，署名“麦囤囤·AI工坊”。

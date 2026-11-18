---
name: bug-reply-assistant
description: |
  缺陷回复助手（KR2 Skill 4）：开发、PM 或客户在 Jira 上回复后，判断 QA 下一步做什么，起草英文回复，
  过一道分级检查（环境 / build / 预期结果必须有），QA 确认一次后发评论、内嵌截图录屏，并顺带关票、
  转回开发、改链接。只按评论文字分类，不看状态。团队通用，任意项目都能用。
  v1 做：验证结论（通过 / 没过 / 部分修复 / 测试完成）、可忽略、延期 / 去 blocks、无法复现，
  「预期行为」只出向 PM 提问的句子；另外提醒等了超过 3 个工作日还没人回的票。
  触发：「回一下 PROJ-123」「这张票怎么回」「开发说修好了，帮我回复 / 关票」「验证过了帮我写评论」
  「没过，转回开发」「开发说 can be ignored」「开发说是预期行为」「开发说复现不了」「去掉 blocks」
  「看看我有哪些票没回」「哪些票等太久了」「bug reply」「reply to this ticket」。
  区分：新开 bug 票 → bug-report-formatter。
---

# Bug Reply Assistant（缺陷回复助手）

你帮 QA 回复 Jira 上开发、PM、客户的评论。你**不替 QA 判断**是不是 bug、能不能忽略，只给依据、措辞和该做的动作。
所有评论和状态、指派、链接的改动，都要 QA 确认一次后才执行。

设计依据：团队对约 280 张 Jira 票、380 条回复的调研（QA 怎么回、哪里多了来回）。

```bash
J=~/.claude/skills/bug-reply-assistant/scripts/jira.py   # 下文都用 python3 $J <子命令>
```

## v1 范围

| 情况 | 话术 | v1 |
|---|---|---|
| 验证通过 / 没过 / 部分修复 | A / C / D | ✅ |
| 测试完成，见关联 bug | E | ✅ |
| 可忽略 / 不修：接受、追问理由 | H / I | ✅ |
| 延期 / 去掉 blocks | P | ✅ |
| 无法复现：补条件、复现不了先关 | L / M | ✅ |
| 预期行为 | 只出 J（有依据时 J2） | ✅ |
| 待回复提醒 | — | ✅ 最小版 |
| 对客户的回复（交回复核 B、说清环境 O、发版时间 Q） | — | ❌ 只做第 4 步检查，不起草 |
| 发版判定 / 关总票（F / G）、上个版本对比（K）、范围假设（N） | — | ❌ 不起草 |
| 规格待确认（开发在问 PM） | — | ❌ 不起草，提醒等 PM |

v1 不起草的情况：说清楚为什么，给出 QA 下一步该做什么。QA 自己写了回复，照样跑第 4 步检查。
话术原文在 [`references/phrasebook.md`](references/phrasebook.md)，怎么判类型在 [`references/reply-types.md`](references/reply-types.md)。

## 第 0 步：凭证（每个会话第一次用时做）

```bash
python3 $J whoami
```
- 正常会输出名字和 `in_qa_group`。`in_qa_group: false` 时提醒一句：这个人不在 Jira 的 `qa` 组，QA / 非 QA 的区分会不准。
- 退出码 2（`NO_CREDENTIALS`）：
  1. 看**当前项目**的 memory 目录里有没有 `jira-credentials.md`（只看系统提示给出的那个目录，不要用 `~/.claude/projects/*/memory` 通配）。
     有的话按反引号精确取 token（标签的大小写和冒号全半角都不固定）：
     ```bash
     sed -n 's/.*[Tt]oken[：:] *`\([^`]*\)`.*/\1/p' <memory 文件> | head -1 | python3 $J setup --site <xxx.atlassian.net> --email <邮箱>
     ```
  2. 没有就请 QA 自己在提示框里跑（token 不要贴进对话）：
     `! read -s T && echo $T | python3 ~/.claude/skills/bug-reply-assistant/scripts/jira.py setup --site <xxx.atlassian.net> --email <你的邮箱>`
     token 在 https://id.atlassian.com/manage-profile/security/api-tokens 生成。
- 退出码 3（`AUTH_401/403`）：token 失效，同上重新 setup。不要重试。

## 第 1 步：待回复清单（每个会话第一次调用时做）

```bash
python3 $J pending            # 默认 3 个工作日；QA 指定了 N 就加 --days N
```
扫 QA 自己经办 / 报告 / 关注、还没关的票，找出最后一条非 QA 评论之后 QA 还没回过的票，分两组输出：

| 组 | 条件 | 怎么展示 |
|---|---|---|
| `overdue` ⏰ 已超时 | 等了 ≥ N 个工作日（不管有没有 @ QA） | 放最前面。`mentions_qa: true`（在找 QA）的在前，最多列 5 张；没在找 QA 的另起一行带过，提示「可能不需要你回」 |
| `waiting` 📥 等你回 | 还没满 N 天，但评论里 @ 了 QA | 全部列出，等得久的在前 |

格式：

```
⏰ 已超时（≥ 3 个工作日）
  PROJ-456 · 5 天 · Dev A：this issue has been fixed in Android v4.0.0 build 501…
📥 等你回（未超时）
  PROJ-457 · 1 天 · Dev B：Fixed in iOS 4.0.0 (822). Please check.
```
- 两组都空就一句话带过，不要列空标题。
- 「等你回」只收 @ 了 QA 的评论，开发之间的讨论不混进来；超时组不限，因为没人接的票就是这个提醒要抓的。
- 只提醒，不自动处理。QA 说「回一下第二张」就对那张走下面的流程。
- 只有一句「Can be ignored.」没人接、客户等录屏、范围问题 20 天没人答，本质都是没人回，这一步就是为了它们。

## 第 2 步：读票，判类型

```bash
python3 $J context <KEY>      # 评论多时加 --all
```
输出里要用的：`reply_target`（QA 最后一次发言之后的第一条非 QA 评论，就是要回的那条）、`later_non_qa_comment_indexes`（之后还有别人说话）、
`waiting_business_days` / `overdue`、`platform_hints`、`links`、`fixVersions`、`transitions`、`reporter`。

1. 按 [`reply-types.md`](references/reply-types.md) 判类型。只看文字，不看状态。之后还有别的非 QA 评论时，把它们一起读，以最新的意图为准。
2. 判断是不是**客户票**（规则在 reply-types.md 末尾），拿不准就问一句。
3. 数轮次：QA 和对方就同一个问题已经来回两轮还没结论 → **不起草第三轮**，建议转 Slack 或拉上 PM。
4. 票已经是 Done 但回复对象还没人接（例如只有一句 Can be ignored 就被关了）→ 告诉 QA，问要不要补一句回应。
5. `overdue: true` 时在判断里写一句「已经等了 N 个工作日」。

开场用 2–4 行说清楚：

```
PROJ-123 · 回复对象：Dev A 10/28「Can be ignored.」（已等 15 个工作日）
类型：可忽略 → 同意用 H，有疑问用 I
下一步：你觉得这个建议对用户有影响吗？
```

## 第 3 步：给出下一步动作，收集事实

先告诉 QA 现在要去做什么，再问缺的事实。**一次问完，只问回复里真的要用的；能从票里读到的不问。**

| 类型 | 先做什么 | 要 QA 给的 |
|---|---|---|
| 已修复请验证 | 从开发评论抽出端、版本、build、环境，告诉 QA 去哪个包 / 环境验 | 结果（过 / 没过 / 部分），**预期结果**，没过时的现象，截图或录屏 |
| 可忽略 / 不修 | 问 QA 同不同意 | 同意 → 无；不同意 → 用户在什么操作下会有什么影响 |
| 预期行为 | 问 QA 手上有没有**票上能链接的**依据 | 依据链接（规格 / Figma / PM 在票上的评论），PM 是谁 |
| 无法复现 / 要录屏 | 对照票里已有的条件，列出还缺哪几项 | 环境、机型 / OS、账号、数据、录屏和出问题的时间段 |
| 延期 / 去 blocks | 读 `links` 找到那条 blocks | 改关联到哪张票、哪个版本再验 |
| 测试完成 | 读关联 bug | 环境、各端 build |
| 要补充信息（上个版本 / 另一端） | 告诉 QA 先去旧版本 / 另一端复测 | v1 不起草，QA 复测完可以用 A / C 的写法手写，再交给第 4 步检查 |

QA 一句话给的结果（如「STG iOS 812 过了，券显示对了」）要自己拆进字段，不要让 QA 按格式重填。
截图和录屏：QA 给路径或文件名；没给时问一句，客户票和验证没过时一定要有。

## 第 4 步：检查关卡（分级）

起草前逐项检查。**必须拦**的缺了就停下来问；**提醒**的只列出来，不挡。

| 项 | 级别 | 规则 |
|---|---|---|
| 环境 | 🔴 必须拦 | 必须写。要和开发说的一致（开发说 stg 就写 STG，别写成 test）；只在 STG 验过就**只写 STG**，绝不说成生产（调研里有一张票因此多来回两轮、拖了一个月） |
| build | 🔴 必须拦 | App 每个端都要有 build 号；Web 写环境即可 |
| 预期结果 | 🔴 必须拦 | 必须复述「应该是什么样、现在是什么样」，不能只写 works well |
| 端 | 🔴 票涉及多个端时才拦 | `platform_hints` 或标题里有多个端时，每个端都要写清楚验了没有 |
| 截图对得上场景 | 🟡 提醒 | Skill 判断不了，只提醒 QA 核一眼：端、场景、票号对不对 |
| 截图（客户票） | 🔴 客户票必须附 | 客户票没有截图 / 录屏就拦 |
| 票号 | 🟡 提醒 | 附件文件名或 QA 说的票号和当前票不一致时提醒 |
| 预期行为的依据 | 🔴 | 没有票上能链接的依据 → 只能出 J；Slack 转述不算；客户票一律 J，由 PM 定 |
| 发版日期 | 🔴 | 回复里不写发版日期和排期，交给 PM |

**跳过**：被拦下时 QA 可以说「跳过：原因」（例：「跳过 build：Web 后台没有 build 号」）。照常往下走，并把这一项和原因记进第 7 步的日志，用来积累例外情况。
不要替 QA 编原因，也不要自己决定跳过。

## 第 5 步：起草

- **一律英文。** 句子取自 [`phrasebook.md`](references/phrasebook.md) 的 v1 模板，换完不能留下 `{ }`。顺带修正常见英文错误（表在 phrasebook 末尾）。
- **@ 发出回复对象那条评论的人**（用 `reply_target.accountId`），不默认 @ 派单的人。E 模板里的 `cc @{QA lead}` 换成团队的 QA 负责人，第一次用时问一句，之后同一会话沿用。要 @ 别人（PM）时用 `python3 $J user <名字>` 查 accountId，有多个同名就问 QA。
- 草稿写成 Jira wiki 语法：@ 写成 `[~accountid:<id>]`，票号直接写（Jira 会自动转链接），链接直接贴 URL。
- 打回类给两版让 QA 选：**接受**（H / P / M）和**带证据追问**（I / J / L）。
- 「预期行为」：
  - 没依据，或客户票 → J（把规格原文或报 bug 的依据写进去，@PM）。
  - 有票上可链接的依据、非客户票 → J2：引用依据说「looks like expected behavior」，请 PM 确认。不写 "This is expected behavior." 结论由 PM 定。
  - PM 已经在票上确认是预期行为 → H，可以关票。

## 第 6 步：一次确认，然后执行

把要做的事放在一个块里给 QA 看，确认一次就全部执行；QA 可以逐项取消（「不要转状态」「别 @ 他」）。

```
评论（@Dev A）：
  Thanks for confirming. As @Dev A confirmed, I'll close this for now and reopen it if it happens again.
附件：无
后续动作：
  1. 状态 → Done
检查：环境 — / build — / 预期结果 —（接受类回复不需要）
确认发出吗？
```

QA 确认后按顺序执行，每步看返回值：

```bash
# 1) 发评论（草稿写进 scratchpad 里的文件；附件逐个上传，失败不中断，最后汇报）
python3 $J post <KEY> --body-file <scratchpad>/reply-<KEY>.txt --attach <文件1> <文件2>
# 2) 后续动作，按下表
python3 $J transition <KEY> --to Done
python3 $J assign <KEY> --account-id <accountId>
python3 $J relink <KEY> --other <KEY2> --remove-blocks --add-relates
```

`post` 会自动处理附件：文件名去空格、和已有附件重名时加后缀、视频去音轨、iOS 的 HEVC / 可变帧率录屏转成 H.264 30fps（不转 Jira 播不了），
然后把图和视频内嵌成**左对齐、原始尺寸**。视频预览要等 Jira 处理十几秒，没马上出来不要重传。

### 后续动作默认值

| 情况 | 话术 | 默认后续动作 |
|---|---|---|
| 验证通过 | A | 状态 → Done |
| 验证没过 / 部分修复 | C / D | 指派回开发；项目有退回状态（Reopened 等）就一起改 |
| 复现不了，先关 | M | 状态 → Done |
| 接受可忽略 / 不修 / 预期行为（PM 已在票上确认） | H | 状态 → Done |
| 追问理由 / 请 PM 确认 | I / J / J2 | 指派给被问的人，状态不动 |
| 补全复现条件 | L | 指派回问的人，状态不动 |
| 延期 / 去掉 blocks | P | 删 blocks、加 relates，状态不动 |
| 测试完成 | E | 不动 |

- **状态**：`transition --to` 先按 transition 名、再按目标状态名匹配。匹配不到会以退出码 4 列出可选项，拿给 QA 选，不要猜。
- **转回给谁**：发「已修复请验证」的开发 → 关联开发票的经办人 → 都没有就问 QA。回复对象是 PM 或派单的人（如 QA 负责人）时，先问 QA 转给谁。
- 「验证没过」时开发票 / 总票上的状态不要动，只动当前这张 bug 票。

执行完读回确认，用 3–5 行汇报：评论链接、内嵌了哪些文件（有转码的写一句）、状态和经办人现在是什么、哪一步失败了。

## 第 7 步：记日志（每次都记，包括没发出去的）

```bash
python3 $J log --ticket <KEY> --type <类型> --template <A|C|…> --outcome posted|draft_only|cancelled|no_draft \
  --edited yes|no --skip "build: Web 后台没有 build 号" --action "transition:Done" --overdue-days <N>
```
- `--edited`：QA 有没有改你的草稿（措辞改了算 yes，只确认算 no）。
- `--skip`：第 4 步每个被跳过的项一条。
- 日志在 `~/.config/bug-reply-assistant/usage-log.jsonl`，只在本机。`python3 $J stats [--since 2026-12-01]` 出汇总：
  调用次数、各类型数量、草稿不改直接用的比例、跳过关卡的原因。这些数字对应设计文档第 8 节的验收标准。

## 边界

- 不替 QA 判断是不是 bug、能不能忽略、是不是预期行为，只给依据和措辞。
- 不回答发版日期和排期。
- 同一张票来回两轮还没结论，不起草第三轮。
- 不在 QA 确认前发任何评论、改任何状态、指派或链接。
- 新发现的问题不写进回复里顺带报：调用 bug-report-formatter 另开票，再在回复里写票号。

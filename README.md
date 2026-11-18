# Bug Reply Assistant（缺陷回复助手）

> skill 标识符：`bug-reply-assistant` · KR2 Skill 4

一个 Claude Code 技能。开发、PM 或客户在 Jira 上回复后，它判断 QA 下一步做什么，起草英文回复，
检查环境 / build / 预期结果有没有写全，QA 确认一次后发评论、内嵌截图录屏，并顺带关票、转回开发、改链接。
每次打开时先列出等你回的票：已经等了 3 个工作日以上的放最前面提醒，没超时但 @ 了 QA 的也一起列出来。

规则来自团队对约 280 张 Jira 票、380 条回复的调研：QA 的回复怎么写、哪些写法会让票多来回一轮。

## 怎么用

| 你说 | 它做什么 |
|---|---|
| 「回一下 PROJ-123」 | 读票，找到要回的那条评论，判类型，告诉你下一步，起草回复 |
| 「PROJ-456 验过了，STG iOS 812 / Android 501 都好了，券显示对了」 | 起草验证通过的评论 → 你确认 → 发评论 + 内嵌截图 + 改 Done |
| 「PROJ-789 没过，录屏在桌面 PROJ-789.mp4」 | 起草没过的评论 → 你确认 → 发评论 + 内嵌录屏 + 转回开发 |
| 「开发说是预期行为」 | 有票上能链接的依据就引用它请 PM 确认，没有就只出向 PM 提问的句子 |
| 「看看我有哪些票没回」 | 分两组列出：⏰ 等了 ≥ 3 个工作日的；📥 没超时但 @ 了 QA 的 |

**v1 做**：验证结论（通过 / 没过 / 部分修复 / 测试完成）、可忽略、延期 / 去 blocks、无法复现、
「预期行为」只出提问句、待回复提醒。
**v1 不起草**：直接回客户的评论、发版判定、上个版本对比、规格待确认。这些情况它会告诉你原因和下一步，
你自己写的回复它照样帮你检查。

### 检查关卡

| 项 | 级别 |
|---|---|
| 环境、build、预期结果 | 必须有，缺了会拦 |
| 端 | 票涉及多个端时才拦 |
| 截图对不对得上场景 | 只提醒；客户票必须附截图 |

被拦下时可以说「跳过：原因」，原因会记进日志，用来积累例外情况。

### 每次都会问你确认

评论、@ 谁、附件、后续动作（改状态 / 指派 / 改链接）放在一个块里给你看，确认一次后才执行，可以逐项取消。

## 安装

### 第 1 步 — Clone 并软链

整段复制粘贴即可：

```bash
mkdir -p ~/claude-skills ~/.claude/skills
git clone https://github.com/yan-theplant/Bug-Reply-Assistant.git ~/claude-skills/bug-reply-assistant
ln -s ~/claude-skills/bug-reply-assistant ~/.claude/skills/bug-reply-assistant
```

目录名必须**正好**是 `bug-reply-assistant`，和 `SKILL.md` 里的 `name:` 一致。

### 第 2 步 — Jira 凭证

到 https://id.atlassian.com/manage-profile/security/api-tokens 生成一个 API token，然后在终端跑
（`read -s` 输入时不显示，token 不会留在命令历史里）：

```bash
read -s T && echo $T | python3 ~/.claude/skills/bug-reply-assistant/scripts/jira.py setup --site 你的站点.atlassian.net --email 你的邮箱
```

看到 `"in_qa_group": true` 就对了。凭证存在 `~/.config/bug-reply-assistant/credentials.json`（权限 600），只在本机。
不想存文件的话，也可以用环境变量 `JIRA_SITE` / `JIRA_EMAIL` / `JIRA_TOKEN`。

QA / 非 QA 的评论按 Jira 用户组区分，默认组名是 `qa`（和 JQL `membersOf("qa")` 同一个组）；组名不一样就设环境变量 `JIRA_QA_GROUP`。

### 第 3 步 — 验证

新开一个 Claude Code 会话，说「看看我有哪些票没回」。

## 前置依赖

- **python3**：脚本只用标准库。
- **ffmpeg / ffprobe**（推荐，`brew install ffmpeg`）：上传前给视频去音轨，把 iOS 的 HEVC 录屏转成 Jira 能播的 H.264。没装也能用，视频会原样上传。
- **sips**：macOS 自带，用来读截图尺寸。

## 更新

```bash
cd ~/claude-skills/bug-reply-assistant && git pull
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 技能入口：v1 范围、7 步流程、检查关卡、后续动作默认值 |
| `references/phrasebook.md` | 英文话术模板（v1 启用的和以后的）、常见英文错误 |
| `references/reply-types.md` | 开发 / PM / 客户的常见说法 → 回复类型，客户票怎么认 |
| `scripts/jira.py` | Jira REST 封装：`whoami` `context` `pending` `post` `transition` `assign` `relink` `user` `log` `stats` |

`python3 scripts/jira.py -h` 看全部子命令。

## 统计

每次调用都会在本机 `~/.config/bug-reply-assistant/usage-log.jsonl` 记一行（票号、回复类型、草稿有没有改、跳过了哪项检查）。

```bash
python3 ~/.claude/skills/bug-reply-assistant/scripts/jira.py stats --since 2026-12-01
```

输出调用次数、各类型数量、草稿不改直接用的比例、跳过检查的原因，对应设计文档第 8 节的验收标准。

## 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `NO_CREDENTIALS` | 还没 setup | 见第 2 步 |
| `AUTH_401` / `AUTH_403` | token 失效或被撤销 | 重新生成 token，再跑一次 setup |
| `in_qa_group: false` | 你不在 Jira 的 QA 组，或组名不是 `qa` | 找管理员加组，或设 `JIRA_QA_GROUP`；否则 QA / 非 QA 的评论区分会不准 |
| 视频内嵌后一直 Creating preview | Jira 还在处理，或源文件是 HEVC 且本机没装 ffmpeg | 等十几秒；装 ffmpeg 后重新传 |
| `transition` 退出码 4 | 这个项目没有叫这个名字的状态 | 从它列出的可选项里选 |

## 贡献

软链装好后，直接改本仓库文件就能本地生效。话术改 `references/phrasebook.md`，新的说法改 `references/reply-types.md`。
PR 不用指定 reviewer，谁用谁就是 review。

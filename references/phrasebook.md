# QA 标准话术库（英文）

回复**一律用英文**。**A / M / H 是关票的回复，全文不出现任何 @**（包括句中提到开发的地方，写纯文字名字）；只有模板开头带 `@{…}` 的才 @。句子以 QA 实际在用的说法为基础，修掉了语法问题。`{ }` 是要替换的内容，换完不能留下任何 `{ }`。
来源：团队的回复话术调研（约 280 张票、380 条回复）。

## v1 启用的模板

### A — 验证通过
开发说已修复，QA 验过没问题。

```
Checked on {env} {platform} ({build}): {expected result}. It has been fixed.
```
- 必须复述预期结果，只写 "it works well" 容易验错对象。
- 多端：`Checked on STG iOS (774) / Android (483): …`

### C — 验证没过
修复后还能复现。

```
@{dev} Rechecked on {env} {platform} ({build}); the issue can still be reproduced: {what happens}. See the recording at {0:06–0:12}. Please help check again.
```
- 没有录屏就去掉 "See the recording…" 那句；有截图就写 "See the screenshot below."

### D — 部分修复

```
Checked on {env}: {A} is now fixed, but {B} still has the issue: {what happens}.
```

### E — 测试完成，见关联 bug
QA 总票或开发票测完。

```
@{dev/PM} QA has completed testing on {env} (iOS {ver} ({build}) / Android {ver} ({build})). Please see the bugs linked above. cc @{QA lead}
```
- Web 项目把括号里换成 `Web`。没有关联 bug 时最后一句改成 `No issues were found.`

### H — 接受「可忽略 / 不修」
同意开发的判断。**用于「预期行为」时，必须是 PM 已经在票上确认过。**

```
Thanks for confirming. As {dev name} confirmed, I'll close this for now and reopen it if it happens again.
```
- **不 @**：`{dev name}` 写纯文字名字，不要写成 `[~accountid:…]`。
- "for now" 是保留态度的固定说法，不要删。

### I — 追问「可忽略」的理由
开发只说 Can be ignored，QA 觉得有影响。

```
@{dev} Could you share why this can be ignored? When users {action}, it may cause {impact}. If you confirm there's no impact, I'll close it.
```
- 调研里有三张票就是没人接这一句，一直卡在 Staging/UAT。

### J — 回应「预期行为」：请 PM 确认
没有票上可链接的依据，或依据和开发说法冲突。**客户票一律用这句。**

```
@{PM} The spec says {spec text}, so I filed this as a bug. Dev says this is expected behavior. Could you confirm which one is correct?
```
- 手上没有规格原文时，第一句改成 `I filed this as a bug based on {what the bug report was based on}.`

### J2 — 有依据：引用依据，请 PM 定结论
QA 有票上可链接的依据（规格、Figma、PM 在票上的确认），看起来确实是预期行为。非客户票才可以用。

```
@{PM} Per {basis link}, this looks like expected behavior: {one-line summary of the basis}. Could you confirm? I'll close this once you confirm.
```
- 依据只认票上能链接的：规格、Figma、PM 在票上的评论。**Slack 转述不算**（调研里有过当天被推翻的例子）。
- 结论由 PM 定，QA 不写 "This is expected behavior."

### L — 回应「无法复现」：补全复现条件
开发复现不了，或要录屏。

```
Repro details: env {env}, device {model} / OS {ver}, account {account}, data {product code etc.}. The issue appears at {0:06–0:12} in the recording.
```
- 客户或客户侧 PM 要录屏时当天回。

### M — 复现不了，先关

```
Retested on {model} (iOS {ver}) with STG iOS {build}: cannot reproduce anymore. I'll close this for now and reopen it if it happens again.
```

### P — 延期 / 去掉 blocks
开发说下版本修，或不是本票的 blocker。

```
Thanks for checking. I'll remove the blocks link, relate it to {ticket} instead, and verify it in {version}.
```
- 不知道哪个版本就把最后一段改成 `and verify it once it's fixed`。

## 后续版本（v1 不起草）

下面几类先不起草，原因见 SKILL.md「v1 范围」。保留原文供以后启用，也方便 QA 自己手写时参考。

| ID | 场景 | 英文 |
|---|---|---|
| B | 客户票验证通过，交回客户复核 | `@{customer} Checked on STG Web / Android ({build}) / iOS ({build}); it has been fixed. Could you please double-check it?` |
| F | 发版判定：无阻塞 | `QA testing is done. There are no release-blocking issues at the moment. The remaining open tickets are Low/Lowest suggestions and do not block the release: {list}` |
| G | 按流程关总票 | `According to the QA Jira Ticket Workflow, since there are no release-blocking issues and the remaining issues are low priority, I'm okay with closing this QA ticket for now.` |
| K | 回答「上个版本是否正常」 | `Checked on STG {old ver} ({build}) and {new ver} ({build}) with the same steps: {old ver} does not have this issue, but {new ver} does, so this looks like a regression in this version.` |
| N | 范围不明：先声明假设 | `@{PM} Quick question about the QA scope of {ticket}: if {X} is included, we'd need {impact}. For now I'll plan QA as {assumption} and treat {Y} as pending.` |
| O | 说清验过的环境 | `What we verified is STG ({build}). It has not been released to production yet; please check production after the release on {date}.` |
| Q | 客户问发版时间 | `This issue has been fixed in {version}. {PM} will let you know the release date.` |

## 常见英文错误（起草时顺带修正）

| 错 | 对 |
|---|---|
| QA have test completed on STG | QA has completed testing on STG |
| I've completed has completed | Testing has been completed |
| still exist the issue | the issue still exists |
| Have checked in Android(1404) STG | Checked on STG Android (1404) |
| it works well.（只有这一句） | Checked {expected result}; it works as expected. |
| Checked on test（开发说的是 stg） | 环境照开发写的那个写 |

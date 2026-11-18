# 回复类型怎么判

只看**回复对象那条评论的文字**（`context` 输出里的 `reply_target`），不看 Jira 状态：预期行为、可忽略、不修的票最后都是 Done，验证没过也常常不改 Reopened。
同一条评论里有多个意图时，按下表从上往下取第一个命中的。

| 类型 | 典型原话（摘录） | v1 处理 |
|---|---|---|
| 规格待确认 | `和产品确认下` · `could you decide which option? @PM` · 开发 @PM 在问 | **不起草**。提醒 QA 等 PM 结论；超过 N 天没结论再说 |
| 预期行为 | `This is expected behaviour, not a bug` · `仕様です` · `by design` | J / J2，规则见 SKILL.md 第 5 步 |
| 可忽略 / 不修 | `Can be ignored.` · `※ 不修 · Not fixing` · `won't fix` | 同意 → H；有疑问 → I |
| 既有 / 范围外 | `※ 不修 · Existing (pre-dates this feature, out of scope)` · `existed issue` | 同意 → H；对比旧版本（K）是 v1 之外 |
| 延期 | `Fix into 5.5.90` · `not a blocker…remove the "blocks" links?` · `PROJ-789 is not a blocker for this ticket` | P |
| 无法复现 | `I couldn't reproduce this. Can you let me know on what iPhone models…` | 先补条件 → L；QA 自己重测也复现不了 → M |
| 要录屏 / 证据 | `Could you please ask QA to also share a video of the case…` | L（当天回） |
| 要补充信息：上个版本 / 另一端 | `Please confirm previous version.` · `Is Android OK?` | v1 不起草（K）；告诉 QA 先去旧版本或另一端复测，结果用 A/C 的写法手写 |
| 已修复请验证 | `Please check in iOS 5.5.90 (1814).` · `Android v3.4.0 build 483 fix this. Please review.` · `已修复并部署到 stg 环境，请重新测试。` · `this issue has been fixed in Android v4.0.0 build 501…` | 抽出端、版本、build、环境 → QA 去验 → 过了 A，没过 C，部分 D |
| 提测 | `X is now on STG and ready for testing.` | 测完用 E；先看开发写的「不用测 / 待交付」范围 |
| 客户复测 NG | `〜ですが、〜なので再度ご確認お願いします。` · `一旦お戻しします。` | 客户票，v1 不起草；提醒 QA 先核对环境和 build |
| 问环境 | `本番環境でよろしいでしょうか。` | 客户票，v1 不起草（O）；提醒只写验过的环境 |
| 发版判定 | `If no bugs remain, I will inform the client to start UAT.` · `Shall I change this ticket's status to Done?` | v1 不起草（F / G） |
| 问发版时间 | `When will this be released?` | 不回答日期，交给 PM（Q 是 v1 之外） |

## 识别要点

- **开发用 AI 写的固定标题**很好认：`In scope — fixed` → 已修复请验证；`Existing` → 既有 / 范围外；`Not fixing` → 可忽略 / 不修。
- **提测评论常常很空**，只有 `Please check in iOS 5.5.80 (1780).`，有时不写端，或 @ 的是派单的人而不是负责的 QA。抽不到端时看票标题（`platform_hints`）和开发票的关联。
- **环境照开发写的那个**：开发说 stg，回复里就写 STG，不写成 test 或 production。
- **开发在开发票上间接打回**（`PROJ-789 is not a blocker for this ticket`）时，回复对象其实在另一张票，提醒 QA 去那张 bug 票上用 P 回应。
- 没有 `reply_target`（QA 是最后一个说话的）→ QA 是来主动发起的，问一句要写什么（多半是 E，或补充信息）。

## 客户票怎么认

满足任一条就按客户票处理：
- 报告人或回复对象是客户方的人（日文评论、客户公司的人、客户侧 PM），不在 QA 组也不在开发里；
- 标题带客户方的格式（例如客户验收测试的固定前缀）；
- QA 说明是客户票。

拿不准就问 QA 一句，不要猜。

# OPANEL-MVP-007: Dashboard 同构面板集成

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

在现有 runtime dashboard 上集成 Actor Panel。保留全局图和 token/quest/event 区域，新增 actor selector、chunk detail、local edge list、stash、message queue、note/reply controls。视觉目标是工作台，不是营销页。

## Acceptance criteria

- [ ] Dashboard 首屏可以选 Actor，并看到其面板。
- [ ] 面板控件按钮和 API 命令一一对应。
- [ ] Operator panel 为观察态；User panel 为可操作态。
- [ ] 关键操作可键盘完成：选择 actor、选择 edge、nav、随机 edge、随机 reset、选择 message、done/delete、commit。
- [ ] 页面在 1366x768 和移动窄屏下不发生文本重叠。
- [ ] Playwright 或等价 browser smoke 验证图、面板、按钮、队列区域非空且可交互。

## Blocked by

- OPANEL-MVP-003: `docs/issues/OPANEL-MVP-003-cursor-navigation-commands.md`
- OPANEL-MVP-004: `docs/issues/OPANEL-MVP-004-stash-ttl.md`
- OPANEL-MVP-005: `docs/issues/OPANEL-MVP-005-note-reply-artifacts.md`
- OPANEL-MVP-006: `docs/issues/OPANEL-MVP-006-message-queue-panel.md`


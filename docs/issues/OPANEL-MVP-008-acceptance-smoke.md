# OPANEL-MVP-008: MVP 验收脚本和回归边界

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

补一个端到端 smoke，验证从 runtime 启动到 User Actor 操作、Operator 观测、artifact commit、message queue 状态变更的完整路径。不要引入重型前端构建系统。

## Acceptance criteria

- [ ] 一条命令能启动短时 runtime 并访问 dashboard snapshot。
- [ ] Smoke 能创建/选择 User Actor，移动 cursor，收藏 chunk，提交 note。
- [ ] Smoke 能向 actor 发送 message，选择 message，mark done 或 delete。
- [ ] Smoke 能确认 Operator action 改变其 panel state。
- [ ] Smoke 能确认 Human Source 文件未被 note/reply commit 改写。
- [ ] 文档记录 MVP 演示路径和失败排查入口。

## Blocked by

- OPANEL-MVP-007: `docs/issues/OPANEL-MVP-007-dashboard-actor-panel.md`


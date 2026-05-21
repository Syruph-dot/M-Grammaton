# OPANEL-MVP-001: 建立 ActorPanelState 快照协议

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

定义面板级状态对象，让 User 和每个 Operator 都能通过同一结构被观察。后端提供按 actor 查询的 panel snapshot，并在 dashboard snapshot 中暴露 actor 列表和当前选中 actor 的 panel state。

## Acceptance criteria

- [ ] 存在 User Actor，默认绑定到第一个普通 document node。
- [ ] 每个 Operator 的 `current`、MBTI、active quest count、last action 能映射进同一份 panel state。
- [ ] Panel state 至少包含 actor id、actor kind、current node、current node kind/title/content preview、in/out edge summaries、stash、selected message、active messages、blocked messages。
- [ ] `GET /api/actors/{actor_id}/panel` 在 runtime ready 和 not ready 时都有稳定 JSON shape。
- [ ] Focused tests 覆盖 User Actor、Operator Actor、空图、缺失 actor。

## Blocked by

None - can start immediately


# OPANEL-MVP-004: 收藏夹和 TTL

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

实现草图中的“送入收藏夹”和“Chunk 收藏夹列表（有生存时间）”。MVP 收藏夹是 actor-local runtime state，用于短期工作记忆；重启持久化延期。

## Acceptance criteria

- [ ] 当前 chunk 可加入 actor stash。
- [ ] Stash item 包含 node id、title、added_at、expires_at、reason。
- [ ] 过期 item 不再出现在默认列表，可通过 debug flag 显示。
- [ ] 用户可移除 stash item。
- [ ] Operator 自动收藏时和 User 手动收藏时使用同一数据结构。
- [ ] Focused tests 覆盖添加、重复添加、过期过滤、移除。

## Blocked by

- OPANEL-MVP-001: `docs/issues/OPANEL-MVP-001-actor-panel-state.md`


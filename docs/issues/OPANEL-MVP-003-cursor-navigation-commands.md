# OPANEL-MVP-003: Cursor 和导航命令闭环

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

实现草图左侧按钮的最小命令集合：选择出边 chunk、Nav 出边、随机选择出边、cursor 随机重置。命令以 actor 为目标，User Actor 可直接触发；Operator 自动循环也通过同一 panel service 更新状态。

## Acceptance criteria

- [ ] `select_out_edge` 只改变 selected edge，不移动 cursor。
- [ ] `nav_selected_edge` 沿 selected edge 移动 cursor，并清理失效 selection。
- [ ] `random_select_out_edge` 按当前边权抽样或均匀抽样一个 out edge 并高亮。
- [ ] `random_reset_cursor` 绑定到随机 node，空图时返回明确错误。
- [ ] 所有命令产生 panel event，可在 Recent Events 看到。
- [ ] Focused tests 覆盖无出边、失效边、随机重置、User Actor 和 Operator Actor 的状态一致性。

## Blocked by

- OPANEL-MVP-002: `docs/issues/OPANEL-MVP-002-chunk-local-edge-view.md`


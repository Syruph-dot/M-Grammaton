# OPANEL-MVP-002: Chunk 内容和局部边视图

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

把草图中的“Chunk 内容显示”和“局部子图指标、出边摘要列表、入边摘要列表”落成可见面板。MVP 不做动态树布局，先交付可读、可点击、可键盘访问的 1-hop 局部视图。

## Acceptance criteria

- [ ] Dashboard 选中 Actor 后显示 current chunk 的 title、kind、content。
- [ ] Human Source 节点明确只读；Quest/Answer/Note artifact 显示为 artifact。
- [ ] 出边列表显示 target、target kind、weight、selected 状态。
- [ ] 入边列表显示 source、source kind、weight。
- [ ] 点击全局图节点可以切换 User Actor 的 current node，Operator 的 current node 只随其自身 action 更新。
- [ ] 局部视图和全局图共享 node id，不产生第二套身份。

## Blocked by

- OPANEL-MVP-001: `docs/issues/OPANEL-MVP-001-actor-panel-state.md`


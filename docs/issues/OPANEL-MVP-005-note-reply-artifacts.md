# OPANEL-MVP-005: Note / Reply Commit 生成 artifact

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

把“记录你的想法 + Commit”和“Reply 栏 + Commit”落成 artifact 生成路径。Note 绑定当前 chunk；Reply 绑定 selected message 或 selected Quest。所有产物进入 Operator/User artifact store，并作为 graph node 加入同一张图。

## Acceptance criteria

- [ ] Note commit 创建 artifact node，包含 author actor、source current node、content、created_at。
- [ ] Reply commit 对 selected Quest 创建 Answer artifact；对普通 message 创建 Reply/Note artifact。
- [ ] Artifact 与 current chunk 或 Quest 建立 edge。
- [ ] Commit 后 dashboard graph、panel content、quest summary 能刷新。
- [ ] 保存后 `data/human/*.md` 不被改写。
- [ ] Focused tests 覆盖 note commit、quest reply commit、无 selected message 的错误、保存加载后 artifact 可恢复。

## Blocked by

- OPANEL-MVP-002: `docs/issues/OPANEL-MVP-002-chunk-local-edge-view.md`


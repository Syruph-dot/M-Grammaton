# OPANEL-MVP-000: 同构 Actor Panel MVP

Type: Parent
Label: ready-for-agent

## What to build

交付一个最小同构操作面板，让 User 和 LLM Operator 都作为 Actor 拥有同一种 panel state、同一种 cursor/navigation/message/commit 协议。用户可以实时观察任意 Operator 的虚拟面板，也拥有自己的可操作面板。

MVP 不复刻草图中的完整视觉布局；它交付可运行、可观察、可测试的协议和 dashboard 集成。全局图、Operator 状态、Quest、token throughput 复用现有 runtime dashboard。新工作集中在 ActorPanelState、User Actor、局部 chunk/edge 视图、stash、message envelopes、note/reply artifact commit。

## Acceptance criteria

- [ ] Dashboard 可以选择任意 Actor，包括 User 和所有 Operator。
- [ ] 选中 Actor 后显示同一结构的面板：当前 chunk、chunk 内容、入边/出边摘要、收藏夹、消息队列、blocked 队列、reply/note 输入。
- [ ] User Actor 可以用同一套命令移动 cursor、收藏 chunk、提交 note、回复选中消息或 Quest。
- [ ] Operator 自动运行时，其面板状态随 action 实时更新，用户可以观察但不默认接管。
- [ ] 所有 commit 都生成 artifact 节点并链接到当前 chunk 或目标 Quest，不修改 `data/human/*.md`。
- [ ] 后端 focused tests 覆盖 panel snapshot、panel commands、message envelope、artifact commit。

## Child issues

- OPANEL-MVP-001: 建立 ActorPanelState 快照协议
- OPANEL-MVP-002: Chunk 内容和局部边视图
- OPANEL-MVP-003: Cursor 和导航命令闭环
- OPANEL-MVP-004: 收藏夹和 TTL
- OPANEL-MVP-005: Note / Reply Commit 生成 artifact
- OPANEL-MVP-006: Message Queue 面板化
- OPANEL-MVP-007: Dashboard 同构面板集成
- OPANEL-MVP-008: MVP 验收脚本和回归边界

## Blocked by

None - can start immediately


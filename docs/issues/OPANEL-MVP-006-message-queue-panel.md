# OPANEL-MVP-006: Message Queue 面板化

Type: AFK
Label: ready-for-agent

## Parent

OPANEL-MVP-000: `docs/issues/OPANEL-MVP-000-actor-panel-mvp.md`

## What to build

把 runtime 内部 MessageBus 的 per-operator queue 投影为面板可见的 message envelopes。MVP 支持 active queue、blocked queue、selected message、done/delete。blocked 只做手工或 unsupported-message bucket，不做复杂依赖推理。

## Acceptance criteria

- [ ] Message envelope 有稳定 id、recipient actor、type、payload summary、created_at、status。
- [ ] Panel state 显示 active messages 和 blocked messages。
- [ ] `select_message_next` / `select_message_prev` 可改变 selected message。
- [ ] `set_message_done` 把 selected message 标为 done 并从 active queue 移出。
- [ ] `delete_message` 软删除 selected message，不破坏事件审计。
- [ ] Unsupported 或手工 block 的消息进入 blocked queue。
- [ ] Focused tests 覆盖 envelope id、select、done、delete、blocked。

## Blocked by

- OPANEL-MVP-001: `docs/issues/OPANEL-MVP-001-actor-panel-state.md`


# M-Grammaton Runtime — 领域语汇

## Runtime

### AsyncOperator
自主意志循环的独立 Agent。每个 Operator 拥有独立 asyncio Task、独立 Persona、独立决策权。
通过 `run()` 循环中的 4 个核心动作（wander / ask / answer / score）与世界互动。

### OperatorRuntime
调度器，管理所有 Operator 的生命周期（创建、启动、关闭）。持有共享状态（MGraph, QuestBoard, TagManager, MessageBus）。

### RuntimeMonitor
Operator 状态采集器，位于同事件循环内，双模消费：snapshot() 供 TUI 轮询 / subscribe() 供 SSE 推送。

### MessageBus
每个 Operator 一个 asyncio.Queue，支持 broadcast 和 drain（非阻塞清空）。

## 行为

### PATIENCE
Operator 处理 inbox 消息时的耐心阈值。仅由 MBTI 的 J/P 维度决定：J 型 0.9±0.05，P 型 0.8±0.05。
每封消息独立掷骰 `random() > patience` → break 跳出 drain 循环。
纯消费端属性，不影响 Decider 的决策权重。

### wander
在知识图谱中沿边漫游或随机跳跃，刷新当前语义位置。

### ask
在当前节点提出 Quest，关联知识图谱节点，不超过 MAX_ACTIVE_QUESTS。

### answer
检索 AnswerTrace，调用 LLM 生成回复，保存为 AnswerNode。

### score
对他人答案从两个维度评分：match_score（匹配度，0-100）和 novelty_score（新颖度，0-100）。

## 消息

### ClockTick
全局心跳，触发 Operator 决策循环。

### QuestPosted
Operator 提问后广播，其他 Operator 可决定是否回答。

### AnswerSubmitted
有人回答了某个 Quest，asker 可决定是否评分。

### AnswerScored
评分完成，包含 match_score 和 novelty_score。

## MBTI

### Persona
Operator 的人格配置。4 维 16 型，每个维度生成对应风格描述（question_style / answer_style / score_style）。

### PATIENCE 公式
`base = 0.9 if 'J' in mbti else 0.8`，加 `random.uniform(-0.05, 0.05)` 扰动。

### stk decay
MGraph 的 stk 栈可能无限增长。通过延迟重检机制维护栈健康：
- 每 ClockTick 检查 stk 节点占比
- 占比 ≥ 100% → 启动 N=4 个心跳周期的延迟重检计数器
- 计数归零时再次检查：若占比仍 ≥ 100% → 触发 `MGraph.decay_stk()`
- 期间占比降回 100% 以下 → 重置计数器

### 追问（被移除）
追问不建模为独立数据结构。Operator 评分后如认为答案不佳，通过自然决策循环中的 `ask()` 即可隐式实现追问。`MAX_ACTIVE_QUESTS` 天然约束深度。

### 决策器 vs 人格 职责分离
Decider 选 action（做什么），Persona 影响 LLM prompt（怎么做）。MBTI 不通过 Python 权重影响 action 概率，仅通过提示词风格影响输出品质。`RandomDecider` 保持随机选择。

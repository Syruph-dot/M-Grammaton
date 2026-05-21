# M-Grammaton Runtime — 领域语汇

## Content Ownership

### Human Source
Human Source 是人类输入的原始 Markdown 文本。它是珍稀内容，只读保存，Operator 不能改写。系统只能读取、引用、评论、摘要或提出修改意见。人类文件存储在 `data/human/*.md`，保持扁平文档形态。

### Operator Artifact
Operator Artifact 是 Operator 生成的派生内容，例如 Quest、Answer、摘要、评论、建议补丁、评分说明。它可以大量生成，不要求一条产物一个 Markdown 文件。运行时将其聚合存储在 `data/operator/artifacts.json`。

### Artifact Type
Artifact Type 是 Operator Artifact 的产品语义子类，存放在 metadata 中，例如 `note`、`reply`、`actor_message`、`web_page`、`search_report`、`patch_suggestion`。

### External Evidence
External Evidence 是 Operator 从系统外部获取的未验证材料，例如 web search 结果。它直接作为带 provenance 的 Operator Artifact 入图，默认不是 Human Source；web 结果使用 `kind: "artifact"` 与 `metadata.artifact_type: "web_page"` 表达。

### Search Report
Search Report 是外部搜索行动产生候选结果后生成的作文式 Operator Artifact，正文默认中文，以连贯主文段完成材料总结/综述和由材料引发的联想/反思；搜索无结果或失败时不生成。

### Actor Message
Actor Message 是 Actor 之间通信的节点化短文，使用 `kind: "artifact"` 与 `metadata.artifact_type: "actor_message"` 表达。它的主体形式是一篇详细描述的短文章，可包含问题、回答和请求；Message Queue / MessageBus 是对这些 message nodes 的待处理视图和消费结构，可以继续用队列实现。

### Operator Context
Operator Context 是一次行动时显式送入 LLM 或 runtime policy 的可见材料集合，例如 current node、阅读路径、stash、selected message、search snippets、历史 artifact 摘要。它不是 LLM 自带的长期记忆；需要持久化的“想法”必须写成 Graph Node、Artifact、Trace、Stash 或 metadata。

### Memory / Impression Layer
Memory / Impression Layer 是 Phase 3 候选能力：在送入 LLM 的 prompt 前插入一段实时动态维护的记忆/印象内容，供 LLM 参考但不强制使用；维护策略尚未决策。

### Graph Node
Graph Node 是图中的逻辑节点，不等同于文件。节点通过稳定 name 参与边、权重、stk、QuestBoard、AnswerTrace。节点内容可以来自 Human Source，也可以来自 Operator Artifact。

### Graph Topology
Graph Topology 存在于 `data/meta/edges.json` 和 `data/meta/nodes.json`。边只连接 Graph Node，不关心内容实际存储在 Markdown 还是 artifact store。因此 human ↔ operator、human ↔ human、operator ↔ operator 都是同一张图。

### Edit Boundary
Operator 对 Human Source 的任何“修改”都必须表示为新的 Operator Artifact，例如建议、批注或 patch_suggestion。系统不得把这类建议自动写回 human Markdown。若 human Markdown 变化，视为人类编辑后的新源内容。

## Runtime

### AsyncOperator
自主意志循环的独立 Agent。每个 Operator 拥有独立 asyncio Task 和独立决策权；Persona 主要作为 LLM 提示诱导与 UI 展示元数据。
通过 `run()` 循环中的 4 个核心动作（wander / ask / answer / score）与世界互动。

### OperatorRuntime
调度器，管理所有 Operator 的生命周期（创建、启动、关闭）。持有共享状态（MGraph, QuestBoard, TagManager, MessageBus）。

### RuntimeMonitor
Operator 状态采集器，位于同事件循环内，双模消费：snapshot() 供 TUI 轮询 / subscribe() 供 SSE 推送。

### MessageBus
每个 Operator 一个 asyncio.Queue，支持 broadcast 和 drain（非阻塞清空）。对 actor-level message 而言，队列保存待处理指针和消费状态，消息正文与持久化身份应落在 `actor_message` artifact node 上。

## 行为

### PATIENCE
Operator 处理 inbox 消息时的耐心阈值。它属于 inbox 消费节奏；是否由 Persona/MBTI 参与推导必须按功能询问用户。
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
Operator 的提示诱导与 UI 展示元数据。它可以影响 LLM 输出的语气、措辞和角色感；任何新系统若想让 Persona/MBTI 参与行为，必须先询问用户并记录具体决策。

### PATIENCE 来源
PATIENCE 的来源不是全局固定规则。若某次实现想让 Persona/MBTI 参与 PATIENCE，必须先询问用户并记录该功能的决策。

### stk decay
MGraph 的 stk 栈可能无限增长。通过延迟重检机制维护栈健康（编码于 `OperatorRuntime._check_stk_decay()`）：
- 每 ClockTick 检查 stk 节点占比
- 占比 ≥ 100% → 启动 STK_DECAY_TICKS=4 个心跳周期的延迟重检计数器
- 计数器递减期间占比降回 100% 以下 → 重置计数器，取消 decay
- 计数归零时再次检查：若占比仍 ≥ 100% → 触发 `MGraph.decay_stk()`
- 此机制实质是 Schmitt 触发器的简化版（去掉了回差，保留了延迟确认）

### 追问（被移除）
追问不建模为独立数据结构。Operator 评分后如认为答案不佳，通过自然决策循环中的 `ask()` 即可隐式实现追问。`MAX_ACTIVE_QUESTS` 天然约束深度。

### 决策器 vs 人格 职责分离
Decider 选 action（做什么），Persona 诱导 LLM 表达（怎么说）并可展示在 UI。Persona/MBTI 是否参与 PATIENCE、action 概率、工具选择、权重变化或持久化边界，必须按功能逐项询问用户，不允许默认接入。

## Flagged ambiguities

- 已决议：不要再为 MBTI/Persona 预设系统影响。新增功能如希望让 MBTI/Persona 参与行为，必须当场询问用户并将结果写入文档。
- External Evidence 是否需要入图前人工审批已决议：Phase 2 直接入图，但必须标记为 unverified，并记录来源 URL、查询、抓取时间、backend 和 actor。
- `web_page` 不作为顶层 Graph Node kind；它是 Operator Artifact 的 Artifact Type，即 `kind: "artifact"` + `metadata.artifact_type: "web_page"`。
- 搜索结果采用 snippet-first。一次搜索行动若导入了 `web_page` snippet 节点，还必须生成一个 `search_report`，正文以默认中文的“总结/综述 + 联想/反思”式连贯主文段持久化，不输出 JSON 或列表；无结果或失败只记录 monitor event，不写 report。
- 搜索生成 `search_report` 后，Operator cursor 不自动移动到 report，仍留在触发搜索的节点；report 只能通过显式导航、stash 或后续 action 进入当前上下文。
- 搜索生成 `search_report` 后，report 自动进入该 Operator 的 stash，reason 为 `search_report`；单个 `web_page` 不自动进入 stash。
- `search_report` 和 `web_page` 作为 Graph Node 对所有 Actor 全局可见，但不会默认广播到 User 或其他 Operator 的消息队列；只有显式 `send_message` 才产生 actor-level message。
- Actor-level message 可以继续使用队列数据结构作为收件箱/待办实现，但消息的表现形式和持久化形式应是 `actor_message` artifact node；队列项引用 message node，并保存 selected/done/deleted 等处理状态。
- Phase 2 不实现独立 Memory / Impression Layer。Phase 3 可考虑将动态维护的记忆/印象内容插入 prompt 前部，作为可用但非强制使用的 LLM 上下文。

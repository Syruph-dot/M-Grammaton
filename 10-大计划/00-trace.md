明确：**所有分数统一采用百分制 `0-100`**，每个答案按 **两个维度** 评分：

```text
scores[i] = [匹配度, 新颖度]   # 参考答案匹配性 + 合理新颖性
```

每个维度独立百分制。路径反馈阈值为：

```text
avg([match, novelty]) > 80  -> 整条 evidence path 正反馈
avg([match, novelty]) <= 80 -> 整条 evidence path 负反馈
```

不再使用 `0.8` 或 `0.0-1.0` 语义。

**分阶段补全计划**

**Phase 1: 评分语义统一**
目标：把 Quest/Operator 里的评分明确成百分制 + 双维度 `[匹配度, 新颖度]`，并加校验。

改动点：
- `QuestNode.scores` 存 `None | tuple[float, float]`，合法范围 `0 <= score <= 100`（每个维度独立）
- `QuestBoard.set_score()` 接受 `(match_score, novelty_score)` 两个参数，各自拒绝越界
- `Operator.score_answer()` 以双维度平均值 `avg > 80` 作为 reaction 阈值（替代旧 `>= 0.5`）

验证：
- 测试 (80, 80)、(80.1, 0)、(100, 100)、(0, 0)、(-1, 50)、(50, 101) 等边界
- commit: `feat: normalize quest scores to percentage scale`
- 然后停下等你审查

**Phase 2: 引入 AnswerTrace**
目标：让一个答案绑定一条阅读路径。

新增概念：
```text
AnswerTrace
- quest_name
- answer_index
- answerer_id
- node_names
- edge_refs 或 edge endpoint pairs
- score
- feedback_applied
```

第一版建议放在 `QuestNode.answer_traces`，和 `answers/from_ids/scores` 按 index 对齐。

验证：
- 提交答案时能保存 trace
- trace 和 answer index 一一对应
- commit: `feat: bind quest answers to reading traces`
- 停下等你审查

**Phase 3: Operator 阅读路径**
目标：答题前必须读一定数量的节点。

新增：
```text
Operator.read_for_quest(graph, quest, node_limit=3)
```

行为：
- 从 Operator 当前节点或 quest 关联起点出发
- 沿 `sample_l2()` 走
- 每一步记录经过的 `edge`
- 读取每个节点的 `content`
- 返回 `read_nodes, path_edges, context_text`

验证：
- `node_limit=3` 时最多读 3 个节点
- 有边时 trace 记录 edge
- 无边时能优雅返回已有节点上下文
- commit: `feat: add operator quest reading paths`
- 停下等你审查

**Phase 4: 答案生成绑定路径**
目标：`answer_quest()` 不再直接模板回答，而是先阅读，再把答案和路径绑定。

第一版可仍用规则生成答案，但必须包含 trace：
```text
read_for_quest()
-> answer_text
-> board.submit_answer(..., trace=...)
```

验证：
- 每个答案都有对应 trace
- trace 中记录了实际读过的节点和边
- commit: `feat: record reading trace when answering quests`
- 停下等你审查

**Phase 5: 评分后整条路径反馈**
目标：实现你的核心策略。

规则：
```python
match_score, novelty_score = quest.scores[answer_index]
avg_score = (match_score + novelty_score) / 2
reaction = avg_score > 80
for edge in answer_trace.path_edges:
    insert_response(reaction, edge)
answer_trace.feedback_applied = True
```

要求：
- 只反馈 evidence path
- 不反馈导航到 quest 的路径
- 防止重复评分导致重复反馈
- 如果重新评分，第一版先拒绝二次反馈，后续再设计回滚/重放

验证：
- 81 分 avg 路径全部正反馈
- 80 分 avg 路径全部负反馈
- 同一答案重复评分不重复写入 `stk`
- commit: `feat: apply score feedback to answer reading paths`
- 停下等你审查

**Phase 6: Demo 可观察化**
目标：让运行结果能看清“答案-路径-反馈”。

输出示例：
```text
Bob answered quest_1
path: node_2 -> node_4 -> node_0
scores: [86, 72]  (match=86, novelty=72)
avg: 79
feedback: negative
affected_edges: 2
```

验证：
- `run_quest_demo.py` 能显示每个答案的路径和反馈方向
- commit: `chore: show answer trace feedback in quest demo`
- 停下等你审查

**Phase 7: 持久化补齐**
目标：把 `AnswerTrace`、百分制分数、`feedback_applied` 保存下来。

注意：当前工作树没有可见 `simulation.py` 源文件，只有旧记忆里提到过，所以这一阶段开始前要先核实现有持久化入口。如果没有，就按 `01-概念/持久化设计.md` 新增最小 save/load。

验证：
- 保存后重载，answer trace 不丢
- 已应用反馈的 trace 不会重放
- commit: `feat: persist quest answer traces`
- 停下等你审查

**Phase 8: LLM 接入预留**
目标：把规则答案替换成 LLM 答案，但不改变路径学习机制。

接口：
```text
context_text + quest.content + operator persona
-> answer_text
```

路径仍由 Python 记录，评分仍按百分制双维度，反馈仍按 `avg > 80`。

commit: `feat: add llm-ready answer generation interface`
- 停下等你审查

执行时我会严格按这个节奏：**一个 Phase 完成、测试通过、提交一个 commit、向你汇报 commit 和验证结果，然后等待你审查确认再进入下一 Phase。**
"""决策器 —— 控制 AsyncOperator 的行为选择。

保留 RandomDecider，新增 EnhancedDecider（softmax + temperature + 6 信号源）。
"""

import math
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    type: str
    target: Any = None


class Decider(ABC):
    @abstractmethod
    async def choose(self, operator, graph, board) -> Action:
        ...


# ── 信号源 ─────────────────────────────────


class SignalSource(ABC):
    """信号源：返回 {action: delta} 映射，delta > 0 鼓励，delta < 0 抑制。"""

    @abstractmethod
    async def score(self, operator, graph, board) -> dict[str, float]:
        ...


class MessagePendingSignal(SignalSource):
    """active_messages > 0 → 鼓励 reply_to_message。"""

    async def score(self, operator, graph, board) -> dict[str, float]:
        active = len([m for m in operator.panel.active_messages
                      if getattr(m, 'status', 'active') == 'active'])
        if active == 0:
            return {}
        delta = min(1.5, 0.3 * active)
        return {"reply_to_message": delta}


class QuestPressureSignal(SignalSource):
    """开放 quest 多 → 鼓励 answer；无 → 鼓励 ask。"""

    async def score(self, operator, graph, board) -> dict[str, float]:
        own_quests = board.submitted_by(operator.id)
        open_quests = board.available_for(operator.id)
        deltas = {}
        if len(own_quests) < getattr(operator, 'MAX_ACTIVE_QUESTS', 3):
            deltas["ask"] = 0.3
        if open_quests:
            deltas["answer"] = min(0.8, 0.2 * len(open_quests))
            deltas["score"] = min(0.4, 0.1 * len(open_quests))
        return deltas


class GraphFrontierSignal(SignalSource):
    """出边少 → 鼓励 wander / search_web。"""

    async def score(self, operator, graph, board) -> dict[str, float]:
        try:
            node = operator.current.get()
        except Exception:
            return {}
        out_count = len(node.outlinks)
        deltas = {}
        if out_count == 0:
            deltas["wander"] = 0.8
            deltas["search_web"] = 0.6
        elif out_count < 3:
            deltas["wander"] = 0.3
            deltas["search_web"] = 0.2
        return deltas


class StashPressureSignal(SignalSource):
    """stash 有内容 → 鼓励 read_stash。"""

    async def score(self, operator, graph, board) -> dict[str, float]:
        stash_size = len(operator.panel.stash)
        if stash_size == 0:
            return {}
        return {"read_stash": min(0.6, 0.15 * stash_size)}


class StkPressureSignal(SignalSource):
    """stk 栈满 → 鼓励 ask 制造互动。"""

    async def score(self, operator, graph, board) -> dict[str, float]:
        if not graph.V:
            return {}
        total_stk = sum(len(getattr(n, "stk", []) or []) for n in graph.V)
        ratio = total_stk / len(graph.V)
        if ratio < 0.5:
            return {}
        return {"ask": min(0.5, ratio * 0.3)}


class BudgetSignal(SignalSource):
    """token 预算紧张 → 抑制 LLM-heavy actions。"""

    async def score(self, operator, graph, board) -> dict[str, float]:
        pool = getattr(getattr(operator, 'llm_client', None), 'request_pool', None)
        if pool is None:
            return {}
        from request_pool import RequestPool
        if not isinstance(pool, RequestPool):
            return {}
        used = getattr(pool, '_used_tokens', 0)
        budget = getattr(pool, 'token_budget', 250_000)
        if budget <= 0:
            return {}
        ratio = used / budget
        if ratio < 0.5:
            return {}
        factor = -min(1.0, (ratio - 0.5) * 2)
        return {
            "ask": factor * 0.5,
            "answer": factor * 0.3,
            "search_web": factor * 0.4,
        }


# ── 默认信号集 ─────────────────────────────


def default_signals() -> list[SignalSource]:
    return [
        MessagePendingSignal(),
        QuestPressureSignal(),
        GraphFrontierSignal(),
        StashPressureSignal(),
        StkPressureSignal(),
        BudgetSignal(),
    ]


DEFAULT_BASE_WEIGHTS: dict[str, float] = {
    "wander": 1.0,
    "ask": 0.5,
    "answer": 0.8,
    "score": 0.3,
    "idle": 0.2,
    "sleep": 0.1,
    "stash_current": 0.4,
    "send_message": 0.3,
    "reply_to_message": 0.6,
    "search_web": 0.3,
    "read_stash": 0.3,
}

PHASE1_ACTIONS = {"wander", "ask", "answer", "score", "idle", "sleep"}
PHASE2_ACTIONS = {"stash_current", "send_message", "reply_to_message",
                  "search_web", "read_stash"}


# ── EnhancedDecider ──────────────────────────


@dataclass
class DecisionTrace:
    actor_id: str = ""
    temperature: float = 0.0
    chosen: str = ""
    raw_scores: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)
    top_signals: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "actor_id": self.actor_id,
            "temperature": self.temperature,
            "chosen": self.chosen,
            "raw_scores": dict(self.raw_scores),
            "probabilities": dict(self.probabilities),
            "top_signals": list(self.top_signals),
        }


class EnhancedDecider(Decider):
    """Softmax + temperature 决策器。

    score(action) = base_weight + Σsignal_deltas - repeat_penalty
    prob(action) = softmax(score / temperature)
    """

    def __init__(
        self,
        signals: list[SignalSource] | None = None,
        base_weights: dict[str, float] | None = None,
        temperature: float = 0.3,
        repeat_penalty: float = 0.15,
        seed: int | None = None,
    ):
        self.signals = signals if signals is not None else default_signals()
        self.base_weights = dict(base_weights or DEFAULT_BASE_WEIGHTS)
        self.temperature = temperature
        self.repeat_penalty = repeat_penalty
        self._rng = random.Random(seed)
        self._last_action: str | None = None
        self._last_trace: DecisionTrace | None = None

    @property
    def last_trace(self) -> DecisionTrace | None:
        return self._last_trace

    async def choose(self, operator, graph, board) -> Action:
        scores = dict(self.base_weights)

        # 1. 信号源注入
        top_signals: list[dict] = []
        for signal in self.signals:
            try:
                deltas = await signal.score(operator, graph, board)
            except Exception:
                continue
            for action, delta in deltas.items():
                if delta != 0:
                    scores[action] = scores.get(action, 0) + delta
                    top_signals.append({
                        "name": signal.__class__.__name__,
                        "action": action,
                        "delta": round(delta, 4),
                    })

        # 2. 重复惩罚
        if self._last_action and self._last_action in scores:
            scores[self._last_action] -= self.repeat_penalty

        # 3. search_web 冷却硬门
        now = time.time()
        if operator.panel.search_cooldown_until > now:
            scores["search_web"] = 0.0

        # 4. 只对当前可执行的动作做 softmax
        available = set(scores.keys()) & (PHASE1_ACTIONS | PHASE2_ACTIONS)
        available_scores = {a: max(0.001, scores.get(a, 0.001)) for a in available}

        # 5. Softmax with temperature
        keys = list(available_scores.keys())
        values = [available_scores[k] for k in keys]
        if self.temperature < 0.001:
            # 确定性：选最大
            chosen_type = max(keys, key=lambda k: available_scores[k])
            probs = {k: 1.0 if k == chosen_type else 0.0 for k in keys}
        else:
            scaled = [v / self.temperature for v in values]
            exp_v = [math.exp(v) for v in scaled]
            total = sum(exp_v)
            if total <= 0:
                probs_list = [1.0 / len(keys)] * len(keys)
            else:
                probs_list = [v / total for v in exp_v]
            probs = dict(zip(keys, probs_list))
            chosen_type = self._rng.choices(keys, weights=probs_list, k=1)[0]

        # 6. 目标
        target = None
        if chosen_type == "answer":
            open_quests = board.available_for(operator.id)
            if open_quests:
                target = open_quests[0]
        elif chosen_type == "score":
            own_quests = board.submitted_by(operator.id)
            if own_quests:
                target = own_quests[0]

        # 7. Trace
        self._last_trace = DecisionTrace(
            actor_id=operator.id,
            temperature=self.temperature,
            chosen=chosen_type,
            raw_scores=dict(scores),
            probabilities=probs,
            top_signals=sorted(top_signals,
                               key=lambda x: -abs(x["delta"]))[:8],
        )

        self._last_action = chosen_type
        return Action(type=chosen_type, target=target)


class RandomDecider(Decider):
    """原 MVP 随机决策器 —— 保持可用。"""

    MAX_ACTIVE_QUESTS = 3

    def __init__(self, seed=None):
        self._rng = random.Random(seed)

    async def choose(self, operator, graph, board) -> Action:
        own_quests = board.submitted_by(operator.id)
        open_quests = board.available_for(operator.id)

        choices = [("wander", 0.25), ("idle", 0.15)]

        if len(own_quests) < self.MAX_ACTIVE_QUESTS:
            choices.append(("ask", 0.25))

        if open_quests:
            choices.append(("answer", 0.20))

        if own_quests:
            choices.append(("score", 0.15))

        chosen = self._rng.choices(
            [c[0] for c in choices],
            weights=[c[1] for c in choices],
            k=1,
        )[0]

        target = None
        if chosen == "answer" and open_quests:
            target = open_quests[0]
        elif chosen == "score" and own_quests:
            target = own_quests[0]

        return Action(type=chosen, target=target)

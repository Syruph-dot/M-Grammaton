"""决策器 —— 控制 AsyncOperator 的行为选择。"""

import random
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


class RandomDecider(Decider):
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
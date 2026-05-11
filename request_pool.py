"""LLM 请求池与 token 窗口限流。"""

from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Condition, Thread
from time import monotonic


@dataclass(slots=True)
class PoolResult:
    value: object
    tokens: int


@dataclass(slots=True)
class _QueuedRequest:
    fn: object
    future: Future


class RequestPool:
    def __init__(self, window_seconds: float = 15.0, token_budget: int = 250_000):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")

        self.window_seconds = float(window_seconds)
        self.token_budget = int(token_budget)
        self._pending = deque()
        self._condition = Condition()
        self._cycle_start: float | None = None
        self._used_tokens = 0
        self._closed = False
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, fn):
        future: Future = Future()
        with self._condition:
            if self._closed:
                raise RuntimeError("request pool is closed")
            self._pending.append(_QueuedRequest(fn=fn, future=future))
            self._condition.notify()
        return future.result()

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            while self._pending:
                request = self._pending.popleft()
                request.future.set_exception(RuntimeError("request pool is closed"))
            self._condition.notify_all()
        self._worker.join(timeout=1)

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    def _reset_cycle_if_needed(self, now: float) -> None:
        if self._cycle_start is None or now - self._cycle_start >= self.window_seconds:
            self._cycle_start = now
            self._used_tokens = 0

    def _run(self):
        while True:
            with self._condition:
                while not self._closed and not self._pending:
                    self._condition.wait()
                if self._closed:
                    return

                now = monotonic()
                self._reset_cycle_if_needed(now)

                while not self._closed and self._pending and self._used_tokens >= self.token_budget:
                    assert self._cycle_start is not None
                    remaining = self.window_seconds - (now - self._cycle_start)
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                    now = monotonic()
                    self._reset_cycle_if_needed(now)

                if self._closed:
                    return
                if not self._pending:
                    continue

                request = self._pending.popleft()

            try:
                result = request.fn()
            except Exception as exc:
                with self._condition:
                    request.future.set_exception(exc)
                    self._condition.notify_all()
                continue

            tokens = int(getattr(result, "tokens", 0) or 0)
            value = getattr(result, "value", result)
            with self._condition:
                self._used_tokens += max(0, tokens)
                request.future.set_result(value)
                self._condition.notify_all()
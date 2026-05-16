from async_llm_client import AsyncLLMClient


def test_extract_usage_prefers_total_tokens():
    data = {"usage": {"total_tokens": 42, "prompt_tokens": 20, "completion_tokens": 22}}
    assert AsyncLLMClient._usage_tokens(data, [], "") == (42, "reported")


def test_extract_usage_sums_prompt_and_completion_tokens():
    data = {"usage": {"prompt_tokens": 11, "completion_tokens": 7}}
    assert AsyncLLMClient._usage_tokens(data, [], "") == (18, "reported")


def test_extract_usage_falls_back_to_estimate():
    messages = [{"role": "user", "content": "hello world"}]
    tokens, source = AsyncLLMClient._usage_tokens({}, messages, "reply")

    assert tokens >= 1
    assert source == "estimated"


class _FakeMonitor:
    def __init__(self):
        self.events = []

    def report_tokens(self, **kwargs):
        self.events.append(kwargs)


def test_report_tokens_accepts_custom_telemetry_action():
    monitor = _FakeMonitor()
    client = AsyncLLMClient.__new__(AsyncLLMClient)
    client.monitor = monitor
    client.operator_id = "system"

    client._report_tokens([], "摘要", {"usage": {"total_tokens": 9}}, action="summary")

    assert monitor.events == [
        {
            "operator_id": "system",
            "action": "summary",
            "tokens": 9,
            "source": "reported",
        }
    ]

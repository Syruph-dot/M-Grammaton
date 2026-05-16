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

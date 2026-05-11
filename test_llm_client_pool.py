from config import Config
from llm_client import LLMClient


class _DummyUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class _DummyMessage:
    def __init__(self, content):
        self.content = content


class _DummyChoice:
    def __init__(self, content):
        self.message = _DummyMessage(content)


class _DummyResponse:
    def __init__(self, content, total_tokens):
        self.choices = [_DummyChoice(content)]
        self.usage = _DummyUsage(total_tokens)


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


class _SpyPool:
    def __init__(self):
        self.tokens = []

    def submit(self, fn):
        result = fn()
        self.tokens.append(result.tokens)
        return result.value

    def close(self):
        return None


def test_llm_client_routes_through_request_pool_and_uses_usage_tokens():
    responses = [
        _DummyResponse("plain reply", 17),
        _DummyResponse('{"score_match": 88, "score_novelty": 77}', 23),
    ]
    fake_client = _FakeClient(responses)
    pool = _SpyPool()
    client = LLMClient(Config(api_key="x"), client=fake_client, request_pool=pool)

    assert client.chat([{"role": "user", "content": "hello"}]) == "plain reply"
    assert client.chat_json([{"role": "user", "content": "hello"}]) == {
        "score_match": 88,
        "score_novelty": 77,
    }
    assert pool.tokens == [17, 23]
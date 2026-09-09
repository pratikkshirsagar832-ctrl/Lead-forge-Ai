"""LLM query expansion tests — offline (fake OpenAI-compatible client)."""
import json

from llm_queries import _extract_queries, make_query_expander


# ---------------------------------------------------------------------------
# Fakes (shape-compatible with GptClassifier: ._client.chat.completions.create)
# ---------------------------------------------------------------------------

class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, responder):
        self._responder = responder
        self.calls = 0
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return self._responder(kwargs)


class _Chat:
    def __init__(self, responder):
        self.completions = _Completions(responder)


class _Client:
    def __init__(self, responder):
        self.chat = _Chat(responder)


class FakeClassifier:
    """Just the attributes make_query_expander touches."""

    def __init__(self, responder=None, *, with_client=True):
        self.model = "fake-model"
        self.calls = 0
        self._client = _Client(responder) if with_client else None


def _ok_response(phrases):
    return _Response(json.dumps({"queries": phrases}))


# ---------------------------------------------------------------------------
# _extract_queries
# ---------------------------------------------------------------------------

def test_extract_queries_cleans_and_dedupes():
    out = _extract_queries(json.dumps({"queries": [
        "need a video editor asap",
        "  anyone   know a good  editor  ",
        "need a video editor asap",  # duplicate
        "x",  # too short
        "a" * 120,  # too long
        42,  # wrong type
    ]}))
    assert out == ["need a video editor asap", "anyone know a good editor"]


def test_extract_queries_filters_seller_language():
    out = _extract_queries(json.dumps({"queries": [
        "I offer video editing services",
        "we provide the best editors",
        "hire me for editing",
        "available for work editing",
        "apply now video editor role",
        "need a video editor asap",
    ]}))
    assert out == ["need a video editor asap"]


def test_extract_queries_handles_garbage():
    assert _extract_queries("not json at all") == []
    assert _extract_queries(json.dumps(["a", "b"])) == []  # not an object
    assert _extract_queries(json.dumps({"other": []})) == []  # missing key
    assert _extract_queries(None) == []


# ---------------------------------------------------------------------------
# make_query_expander
# ---------------------------------------------------------------------------

def test_expander_success_counts_call_and_uses_model():
    clf = FakeClassifier(lambda kwargs: _ok_response(["need a video editor", "editor for youtube channel"]))
    expand = make_query_expander(clf, lead_type="need_freelancer")
    out = expand("video editing")
    assert out == ["need a video editor", "editor for youtube channel"]
    assert clf.calls == 1  # counted toward the per-search DeepSeek ceiling
    assert clf._client.chat.completions.last_kwargs["model"] == "fake-model"
    assert "video editing" in clf._client.chat.completions.last_kwargs["messages"][0]["content"]


def test_expander_lead_type_reaches_prompt():
    clf = FakeClassifier(lambda kwargs: _ok_response(["looking for an agency"]))
    expand = make_query_expander(clf, lead_type="our_agency")
    expand("video editing")
    prompt = clf._client.chat.completions.last_kwargs["messages"][0]["content"]
    assert "agency" in prompt


def test_expander_provider_error_returns_empty():
    def boom(kwargs):
        raise RuntimeError("API down")

    clf = FakeClassifier(boom)
    expand = make_query_expander(clf, lead_type="need_freelancer")
    assert expand("video editing") == []  # fail-closed, never raises
    assert clf.calls == 1  # the attempt still counted


def test_expander_invalid_json_returns_empty():
    clf = FakeClassifier(lambda kwargs: _Response("garbage, not json"))
    expand = make_query_expander(clf, lead_type="need_freelancer")
    assert expand("video editing") == []


def test_expander_without_client_returns_empty():
    clf = FakeClassifier(with_client=False)
    expand = make_query_expander(clf, lead_type="need_freelancer")
    assert expand("video editing") == []
    assert clf.calls == 0  # no spend when there is no client at all

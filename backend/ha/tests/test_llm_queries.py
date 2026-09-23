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


# ---------------------------------------------------------------------------
# v2: per-mode direction + structured vocabulary
# ---------------------------------------------------------------------------

def test_need_agency_expansion_asks_for_agency_buyers_not_freelancers():
    """Regression: need_agency searches used to get the freelancer label."""
    clf = FakeClassifier(lambda kwargs: _ok_response(["looking for an seo agency"]))
    make_query_expander(clf, lead_type="need_agency")("seo")
    prompt = clf._client.chat.completions.last_kwargs["messages"][0]["content"]
    assert "hire an AGENCY" in prompt
    assert "independent FREELANCER" not in prompt
    assert '"looking for a seo agency"' in prompt  # examples use the real service


def test_need_freelancer_expansion_asks_for_freelancers_not_agencies():
    clf = FakeClassifier(lambda kwargs: _ok_response(["need a video editor"]))
    make_query_expander(clf, lead_type="need_freelancer")("video editing")
    prompt = clf._client.chat.completions.last_kwargs["messages"][0]["content"]
    assert "independent FREELANCER" in prompt
    assert "hire an AGENCY" not in prompt


def test_expansion_carries_service_vocabulary():
    payload = {
        "queries": ["need a reels editor for our brand"],
        "role_nouns": ["video editor", "reels editor"],
        "synonyms": ["short-form editing", "youtube editing", "Video Editor"],
        "not_this_service": ["videographer", "motion designer", 42],
    }
    clf = FakeClassifier(lambda kwargs: _Response(json.dumps(payload)))
    out = make_query_expander(clf, lead_type="need_freelancer")("video editing")
    assert out == ["need a reels editor for our brand"]  # still a plain list of queries
    assert out.role_nouns == ["video editor", "reels editor"]
    assert out.synonyms == ["short-form editing", "youtube editing"]  # case-insensitive dedupe
    assert out.not_this_service == ["videographer", "motion designer"]  # non-strings dropped


def test_parse_expansion_garbage_is_empty():
    from llm_queries import parse_expansion

    for bad in ("not json", "[1,2]", None, {"queries": "x"}):
        out = parse_expansion(bad)
        assert out == [] and out.synonyms == [] and out.not_this_service == []

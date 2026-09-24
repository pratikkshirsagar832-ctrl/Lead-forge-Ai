"""Pytest bootstrap: make the backend package importable from anywhere and
force OFFLINE mode (in-memory store + mock providers) so the suite never
touches real Supabase/OpenAI/SocialCrawl — even when backend/.env has live
credentials."""
import os
import sys
from pathlib import Path

os.environ["MOCK_MODE"] = "1"

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import pytest  # noqa: E402

# Engine-shape env vars that app/services/hyperagent_service._ha_settings()
# writes into os.environ for production; restored around every test so the
# query-builder/engine tests see the code defaults, not production tuning.
_ENGINE_ENV = ("QUERY_STYLE", "FRESHNESS_LADDER", "FULLTEXT_ENRICH", "MAX_ENRICH_PER_SEARCH")


@pytest.fixture(autouse=True)
def _isolate_engine_env(monkeypatch):
    for name in _ENGINE_ENV:
        monkeypatch.delenv(name, raising=False)
    yield

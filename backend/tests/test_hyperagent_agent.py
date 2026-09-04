"""
HyperAgent autonomous-agents tests: LinkedIn system prompt, task builder, result parser.
No network — pure functions.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import hyperagent_agent as ha  # noqa: E402


def test_system_prompt_is_hyperagent_named():
    assert "HYPERAGENT" in ha.LINKEDIN_AGENT_SYSTEM_PROMPT
    assert "browser" in ha.LINKEDIN_AGENT_SYSTEM_PROMPT.lower()
    # it must teach buyer vs seller distinction
    low = ha.LINKEDIN_AGENT_SYSTEM_PROMPT.lower()
    assert "seller" in low or "do not extract" in low


def test_task_builder_builds_search_url():
    t = ha.build_linkedin_task("video editing", "freelancer_needed", "United States", 5, "looking for freelance video editor")
    assert "search/results/content" in t
    assert "looking%20for%20freelance%20video%20editor" in t
    assert "5" in t


def test_task_builder_lead_type_hint_differs():
    freelancer = ha.build_linkedin_task("seo", "freelancer_needed", "", 3, "seo")
    agency = ha.build_linkedin_task("seo", "agency_wanted", "", 3, "seo")
    assert "FREELANCER" in freelancer
    assert "AGENCY" in agency or "agency" in agency


def test_parse_agent_result_keeps_post_url():
    raw = (
        '[{"author_name":"Acme","profile_url":"https://www.linkedin.com/in/acme",'
        '"post_url":"https://www.linkedin.com/feed/update/urn:li:activity:123",'
        '"post_text":"We are looking for a freelance video editor for our brand."}]'
    )
    items = ha.parse_agent_result(raw)
    assert len(items) == 1
    it = items[0]
    assert it["author"]["url"] == "https://www.linkedin.com/in/acme"
    assert it["postUrl"] == "https://www.linkedin.com/feed/update/urn:li:activity:123"
    assert "looking for a freelance video editor" in it["content"]


def test_parse_agent_result_skips_invalid():
    raw = '[{"author_name":"X","post_text":"has content but no profile url"}]'
    assert ha.parse_agent_result(raw) == []


def test_parse_agent_result_handles_markdown_wrap():
    raw = '```json\n[{"author_name":"B","profile_url":"https://www.linkedin.com/in/b","post_text":"Need a freelance editor please."}]\n```'
    items = ha.parse_agent_result(raw)
    assert len(items) == 1


def test_parse_agent_result_empty_and_nonarray():
    assert ha.parse_agent_result("no array") == []
    assert ha.parse_agent_result("{}") == []
    assert ha.parse_agent_result("") == []

"""Full-text enrichment: extraction + fail-closed fetch (offline)."""
import enrich
from enrich import extract_post_text, fetch_full_text

_BODY = ("We're launching our new product next month and need a freelance video editor "
         "to cut 12 short reels. Budget is ready, starting this week - recommendations welcome!")


def test_extracts_json_ld_article_body():
    page = f"""<html><head>
    <meta property="og:description" content="We're launching our new product next month and need...">
    <script type="application/ld+json">{{"@type": "SocialMediaPosting", "articleBody": "{_BODY}"}}</script>
    </head></html>"""
    assert extract_post_text(page) == _BODY  # the LONGEST candidate wins


def test_extracts_og_description_with_entities():
    page = ('<meta content="Need a plumber in Austin this week &amp; budget is set. '
            'Anyone know someone reliable?" property="og:description">')
    assert extract_post_text(page) == ("Need a plumber in Austin this week & budget is set. "
                                       "Anyone know someone reliable?")


def test_login_wall_and_empty_pages_yield_none():
    wall = '<meta property="og:description" content="Sign in to view this post and join LinkedIn today.">'
    assert extract_post_text(wall) is None
    assert extract_post_text("") is None
    assert extract_post_text("<html><body>nothing here</body></html>") is None


def test_fetch_is_fail_closed(monkeypatch):
    monkeypatch.setattr(enrich, "_fetch_html", lambda url, timeout: None)
    assert fetch_full_text("https://www.linkedin.com/posts/x-activity-7372000000000000000-a") is None
    # Non-LinkedIn URLs are never fetched.
    called = []
    monkeypatch.setattr(enrich, "_fetch_html", lambda url, timeout: called.append(url) or "")
    assert fetch_full_text("https://example.com/post") is None
    assert called == []


def test_fetch_returns_extracted_text(monkeypatch):
    page = f'<meta property="og:description" content="{_BODY}">'
    monkeypatch.setattr(enrich, "_fetch_html", lambda url, timeout: page)
    assert fetch_full_text("https://www.linkedin.com/posts/x-activity-7372000000000000000-a") == _BODY

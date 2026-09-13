"""
Integration tests for the crawler -- these hit real websites over the
network via Playwright, so they're slower and require
`playwright install chromium` to have been run.

Run just these: pytest tests/test_crawler.py -v -m integration
"""
import pytest

from src.crawler import _discover_subpage_urls, crawl_domain

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_crawl_real_domain_returns_homepage_and_subpages():
    result = await crawl_domain("supabase.com")
    assert result.pages[0].ok, f"homepage fetch failed: {result.pages[0].error}"
    assert len(result.successful_urls) >= 1
    # homepage HTML should be substantial (rendered JS content, not an empty shell)
    assert len(result.pages[0].html) > 1000


@pytest.mark.asyncio
async def test_crawl_handles_nonexistent_domain_gracefully():
    """This is the resilience requirement in disguise: a totally broken
    domain must produce a failed PageResult, never raise an exception."""
    result = await crawl_domain("this-domain-definitely-does-not-exist-12345.com")
    assert result.pages[0].ok is False
    assert result.pages[0].error  # some error message was captured, not a silent crash


def test_discover_subpage_urls_filters_by_keyword_and_domain():
    fake_html = """
    <a href="/about">About</a>
    <a href="/pricing">Pricing</a>
    <a href="https://external.com/team">External team page</a>
    <a href="/blog/post-1">Unrelated blog post</a>
    """
    urls = _discover_subpage_urls(fake_html, "https://acme.com")
    assert "https://acme.com/about" in urls
    assert "https://acme.com/pricing" in urls
    assert not any("external.com" in u for u in urls)  # off-domain links excluded
    assert not any("blog" in u for u in urls)  # non-keyword paths excluded

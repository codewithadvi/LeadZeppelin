"""
Unit tests for the HTML -> clean text step, using hand-built fake HTML.
No network needed -- this proves the boilerplate-stripping logic works in
isolation, before ever touching a real site.
Run: pytest tests/test_extractor.py -v
"""
from src.crawler import CrawlResult, PageResult
from src.extractor import build_llm_context, clean_page_text, extract_raw_links_and_emails

FAKE_HTML = """
<html>
<head><style>.nav { display: none; }</style><script>console.log('tracking pixel')</script></head>
<body>
    <nav><a href="/">Home</a><a href="/pricing">Pricing</a></nav>
    <main>
        <h1>Acme Corp</h1>
        <p>Acme builds developer tools for backend teams. We help engineers ship faster.</p>
        <div class="team">
            <p>Jane Doe, CEO — <a href="https://linkedin.com/in/janedoe">LinkedIn</a></p>
        </div>
    </main>
    <footer>Copyright 2025 Acme Corp. All rights reserved.</footer>
</body>
</html>
"""


def test_clean_page_text_strips_scripts_and_keeps_content():
    cleaned = clean_page_text(FAKE_HTML)
    assert "console.log" not in cleaned
    assert "Acme builds developer tools" in cleaned


def test_clean_page_text_drops_hrefs_but_keeps_anchor_text():
    """Documents a real trafilatura limitation we discovered: include_links
    keeps the anchor text ("LinkedIn") but not the href URL. This is exactly
    why extract_raw_links_and_emails exists as a separate regex pass."""
    cleaned = clean_page_text(FAKE_HTML)
    assert "LinkedIn" in cleaned
    assert "linkedin.com/in/janedoe" not in cleaned


def test_extract_raw_links_and_emails_recovers_the_linkedin_url():
    links = extract_raw_links_and_emails(FAKE_HTML)
    assert "linkedin.com/in/janedoe" in links


def test_build_llm_context_tags_pages_with_source_url():
    crawl_result = CrawlResult(
        domain="acme.com",
        pages=[
            PageResult(url="https://acme.com/", html=FAKE_HTML, ok=True),
            PageResult(url="https://acme.com/broken", html="", ok=False, error="404"),
        ],
    )
    context = build_llm_context(crawl_result)
    assert "--- PAGE: https://acme.com/ ---" in context
    assert "acme.com/broken" not in context  # failed pages must not leak into context


def test_build_llm_context_handles_all_pages_failed():
    crawl_result = CrawlResult(
        domain="deadsite.com",
        pages=[PageResult(url="https://deadsite.com/", html="", ok=False, error="timeout")],
    )
    context = build_llm_context(crawl_result)
    assert context == ""

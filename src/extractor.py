"""
Turns raw rendered HTML into clean, LLM-friendly text.

Why trafilatura: it's purpose-built for "give me the main readable content"
(same idea as browser Reader Mode). It strips <script>, <style>, SVGs, nav
bars and footers, and keeps headings/paragraphs/links. This matters for two
reasons: (1) token cost -- raw HTML is 90% layout noise, (2) accuracy -- LLMs
extract better from signal without noise than from a haystack.

We do NOT do retrieval-style chunking here (no vector search / map-reduce).
For single company marketing pages, a simple per-page character cap plus
concatenation keeps everything well inside the model's context window while
staying fast and simple. True chunking would be over-engineering for this
input size.
"""
import logging
import re

import trafilatura

from src.config import MAX_CHARS_PER_PAGE
from src.crawler import CrawlResult

logger = logging.getLogger(__name__)

# trafilatura's `include_links` keeps anchor *text* but does not reliably
# keep the href in markdown output (verified empirically -- a "LinkedIn"
# link renders as the word "LinkedIn" with the URL dropped). Since LinkedIn
# URLs and emails are exactly what this pipeline needs, we pull them
# straight out of the raw HTML with regex instead of trusting trafilatura
# to carry them through prose extraction.
LINKEDIN_HREF_PATTERN = re.compile(r'href=["\'](https?://(?:[\w-]+\.)?linkedin\.com/[^"\']+)["\']', re.I)
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# <script>/<style> blocks are the source of two real bugs found while
# testing against stripe.com: (1) Next.js embeds a __NEXT_DATA__ JSON blob
# full of documentation code-sample emails (jane.smith@example.com,
# billing@example.com) that have nothing to do with the actual company
# contact info, and (2) JSON string-escaping inside that blob (> for
# ">") bled into regex matches as garbage like "u003esales@stripe.com".
# Stripping these blocks before running link/email regex fixes both.
SCRIPT_STYLE_PATTERN = re.compile(r'<(script|style)\b[^>]*>.*?</\1>', re.I | re.S)

# Docs/marketing sites are full of placeholder emails in code samples --
# these domains are never real contact points and should never surface as
# "contact points" in the output.
PLACEHOLDER_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.com", "yourdomain.com", "domain.com"}


def _strip_script_and_style(html: str) -> str:
    return SCRIPT_STYLE_PATTERN.sub("", html)


def _is_real_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain not in PLACEHOLDER_EMAIL_DOMAINS


def clean_page_text(html: str) -> str:
    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_tables=False,
        favor_recall=True,    # bias towards keeping content over aggressively trimming it
    )
    return text or ""


def extract_raw_links_and_emails(html: str) -> str:
    """Separate, regex-based signal for links/emails that prose extraction
    tends to drop. Appended to the LLM context as its own section so the
    model can still associate a name (from prose) with a URL (from here).

    Runs on script/style-stripped HTML -- see SCRIPT_STYLE_PATTERN above for
    why that matters (JSON blobs full of doc-sample emails otherwise leak
    straight into the "contact emails" field)."""
    cleaned_html = _strip_script_and_style(html)
    linkedin_urls = sorted(set(LINKEDIN_HREF_PATTERN.findall(cleaned_html)))
    emails = sorted({e for e in EMAIL_PATTERN.findall(cleaned_html) if _is_real_email(e)})

    lines = []
    if linkedin_urls:
        lines.append("LinkedIn URLs found on this page: " + ", ".join(linkedin_urls))
    if emails:
        lines.append("Email addresses found on this page: " + ", ".join(emails))
    return "\n".join(lines)


def build_llm_context(crawl_result: CrawlResult) -> str:
    """Concatenates cleaned text from every successfully-fetched page into a
    single prompt-ready string, tagging each section with its source URL so
    the model (and our confidence scorer) can trace claims back to a page."""
    sections = []
    for page in crawl_result.pages:
        if not page.ok:
            continue
        cleaned = clean_page_text(page.html)
        links_and_emails = extract_raw_links_and_emails(page.html)
        if not cleaned.strip() and not links_and_emails:
            continue
        truncated = cleaned[:MAX_CHARS_PER_PAGE]
        section = f"--- PAGE: {page.url} ---\n{truncated}"
        if links_and_emails:
            section += f"\n\n{links_and_emails}"
        sections.append(section)

    if not sections:
        logger.warning("No extractable text for domain %s", crawl_result.domain)

    return "\n\n".join(sections)

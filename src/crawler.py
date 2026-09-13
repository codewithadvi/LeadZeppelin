"""
Handles all browser automation. This is the only file that imports
playwright -- everything downstream just deals with plain strings (URL ->
HTML), so we could swap Playwright for Selenium/Puppeteer later without
touching any other module.

Why Playwright over requests+BeautifulSoup: modern marketing sites (Next.js,
React) render team/pricing content client-side. A raw `requests.get()` often
returns an near-empty <div id="root"></div> shell. Playwright runs a real
headless Chromium, executes the JS, and only then hands us the HTML.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, async_playwright

from src.config import MAX_SUBPAGES, PAGE_TIMEOUT_MS, SUBPAGE_KEYWORDS

logger = logging.getLogger(__name__)

# Text fragments that show up on common bot-block / challenge pages. If a
# fetched page contains these, we treat it as blocked rather than pretending
# we got real content.
BOT_BLOCK_MARKERS = [
    "checking your browser",
    "attention required",
    "cf-challenge",
    "access denied",
    "are you a robot",
]


@dataclass
class PageResult:
    url: str
    html: str = ""
    ok: bool = False
    error: str = ""


@dataclass
class CrawlResult:
    domain: str
    pages: List[PageResult] = field(default_factory=list)

    @property
    def successful_urls(self) -> List[str]:
        return [p.url for p in self.pages if p.ok]


def _normalize_domain(domain: str) -> str:
    domain = domain.strip()
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    return domain


def _is_bot_blocked(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in BOT_BLOCK_MARKERS)


async def _fetch_page(browser: Browser, url: str, semaphore: asyncio.Semaphore) -> PageResult:
    async with semaphore:
        page = await browser.new_page()
        try:
            # "networkidle" sounds like the right wait condition, but it never
            # fires on sites with persistent background connections (analytics
            # beacons, chat widgets, websockets) -- discovered this against
            # postman.com, which timed out every time despite rendering fine.
            # domcontentloaded + a short fixed settle delay is more reliable.
            response = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(1500)
            if response is None:
                return PageResult(url=url, ok=False, error="no response (DNS/connection failure)")
            if response.status == 404:
                return PageResult(url=url, ok=False, error="404 not found")
            if response.status >= 400:
                return PageResult(url=url, ok=False, error=f"HTTP {response.status}")

            html = await page.content()
            if _is_bot_blocked(html):
                return PageResult(url=url, ok=False, error="bot-block/challenge page detected")
            return PageResult(url=url, html=html, ok=True)
        except Exception as exc:  # noqa: BLE001 - we deliberately swallow all errors here
            return PageResult(url=url, ok=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            await page.close()


def _discover_urls_by_keywords(
    homepage_html: str, base_url: str, keywords: List[str], exclude: List[str] = None
) -> List[str]:
    """Regex-free discovery via simple substring matching on href attributes.
    Deliberately simple: we don't need a full HTML parser here since we only
    want the raw href strings, and extractor.py handles real parsing later.

    `keywords` is parameterized (rather than always SUBPAGE_KEYWORDS) so the
    agentic follow-up hop in pipeline.py can search for terms the LLM itself
    picked -- e.g. "leadership" or "founders" -- instead of only the fixed
    initial list.
    """
    import re

    hrefs = re.findall(r'href=["\'](.*?)["\']', homepage_html, flags=re.IGNORECASE)
    base_host = urlparse(base_url).netloc
    exclude_set = set(exclude or [])

    candidates = []
    seen = set()
    for href in hrefs:
        if href.startswith("mailto:") or href.startswith("javascript:") or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != base_host:
            continue  # stay on the same domain, don't wander off-site
        path = parsed.path.lower()
        if not any(keyword.lower() in path for keyword in keywords):
            continue
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if (
            clean_url not in seen
            and clean_url not in exclude_set
            and clean_url.rstrip("/") != base_url.rstrip("/")
        ):
            seen.add(clean_url)
            candidates.append(clean_url)

    return candidates


def _discover_subpage_urls(homepage_html: str, base_url: str) -> List[str]:
    return _discover_urls_by_keywords(homepage_html, base_url, SUBPAGE_KEYWORDS)[:MAX_SUBPAGES]


def discover_extra_urls(homepage_html: str, base_url: str, keywords: List[str], exclude: List[str]) -> List[str]:
    """Public entrypoint used by the agentic follow-up hop: search for
    additional keywords (chosen by the LLM) that weren't part of the fixed
    initial SUBPAGE_KEYWORDS list, excluding pages already fetched."""
    return _discover_urls_by_keywords(homepage_html, base_url, keywords, exclude=exclude)[:3]


async def fetch_extra_pages(urls: List[str]) -> List[PageResult]:
    """Fetches a small, agent-chosen list of additional URLs. Opens its own
    browser instance -- this only runs on the rare low-confidence path, so
    the extra browser-launch cost is negligible against getting the info."""
    if not urls:
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            semaphore = asyncio.Semaphore(3)
            results = await asyncio.gather(*[_fetch_page(browser, url, semaphore) for url in urls])
            return list(results)
        finally:
            await browser.close()


async def crawl_domain(domain: str) -> CrawlResult:
    base_url = _normalize_domain(domain)
    result = CrawlResult(domain=domain)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            homepage = await _fetch_page(browser, base_url, asyncio.Semaphore(1))
            result.pages.append(homepage)

            if not homepage.ok:
                logger.warning("Homepage fetch failed for %s: %s", domain, homepage.error)
                return result

            subpage_urls = _discover_subpage_urls(homepage.html, base_url)
            logger.info("Discovered %d subpages for %s: %s", len(subpage_urls), domain, subpage_urls)

            semaphore = asyncio.Semaphore(3)  # politeness cap: max 3 concurrent requests/domain
            subpage_results = await asyncio.gather(
                *[_fetch_page(browser, url, semaphore) for url in subpage_urls]
            )
            result.pages.extend(subpage_results)
        finally:
            await browser.close()

    return result

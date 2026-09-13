"""
Two Tavily-backed bonus features:
1. find_linkedin_url -- given a name we already have, find their LinkedIn URL.
2. find_company_leadership -- given ONLY a domain, search the open web for
   who founded/leads the company at all, for when the site itself publishes
   no leadership page (a real, common case found while testing against
   linear.app and notion.so -- they simply don't list execs on marketing
   pages, so there's nothing on-site to enrich with LinkedIn URLs).

Why Tavily over raw Google/SerpAPI: it's built specifically for LLM-agent
use cases -- free tier (1000 searches/month), returns clean structured
results instead of raw SERP HTML you'd have to scrape and parse yourself.
"""
import logging
import re
from typing import List, Optional

import instructor
from groq import Groq
from tavily import TavilyClient

from src.config import GROQ_API_KEY, GROQ_MODEL, TAVILY_API_KEY
from src.models import TeamMember

logger = logging.getLogger(__name__)

LINKEDIN_PATTERN = re.compile(r"https?://(?:[\w-]+\.)?linkedin\.com/in/[\w\-]+/?")


def find_linkedin_url(name: str, company: str) -> Optional[str]:
    if not TAVILY_API_KEY:
        return None

    try:
        client = TavilyClient(api_key=TAVILY_API_KEY)
        query = f'"{name}" {company} LinkedIn'
        response = client.search(query=query, max_results=3)

        for result in response.get("results", []):
            url = result.get("url", "")
            match = LINKEDIN_PATTERN.search(url)
            if match:
                return match.group(0)
            # sometimes the LinkedIn URL is in the snippet content, not the result URL
            content_match = LINKEDIN_PATTERN.search(result.get("content", ""))
            if content_match:
                return content_match.group(0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tavily search failed for %s at %s: %s", name, company, exc)

    return None


LEADERSHIP_EXTRACTION_PROMPT = """You are extracting a company's founders/leadership from web search \
results. You'll see snippets from multiple search results -- some may be irrelevant (wrong company, \
customer testimonials, news about a different topic). Only include people who are clearly founders, \
C-level executives, or leadership at the SPECIFIC company named, based on what the snippets actually \
say. If nothing in the snippets clearly identifies real leadership, return an empty list rather than \
guessing."""


def find_company_leadership(domain: str) -> List[TeamMember]:
    """Broad fallback for when a company's own site publishes no leadership
    page at all (a real outcome, not a bug -- e.g. linear.app, notion.so).
    Searches the open web for "{domain} founders CEO", then runs a small
    structured-extraction pass over the search snippets to pull out actual
    names/roles, filtering out irrelevant results itself (search results for
    a well-known company are noisy: they include news, testimonials, and
    completely unrelated people who happen to share a keyword)."""
    if not TAVILY_API_KEY or not GROQ_API_KEY:
        return []

    try:
        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.search(
            query=f"{domain} founders CEO co-founder leadership team",
            max_results=5,
            include_answer=False,
        )
        snippets = "\n\n".join(
            f"[{r.get('title', '')}]({r.get('url', '')})\n{r.get('content', '')[:600]}"
            for r in response.get("results", [])
        )
        if not snippets.strip():
            return []

        groq_client = instructor.from_groq(Groq(api_key=GROQ_API_KEY), mode=instructor.Mode.TOOLS)
        from src.models import LeadershipSearchResult

        result = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            response_model=LeadershipSearchResult,
            max_retries=2,
            messages=[
                {"role": "system", "content": LEADERSHIP_EXTRACTION_PROMPT},
                {"role": "user", "content": f"Company domain: {domain}\n\nSearch results:\n{snippets}"},
            ],
        )
        return result.team_members
    except Exception as exc:  # noqa: BLE001
        logger.warning("Leadership search failed for %s: %s", domain, exc)
        return []

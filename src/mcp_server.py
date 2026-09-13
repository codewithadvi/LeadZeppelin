"""
Exposes the same pipeline building blocks as MCP tools, so any MCP client
(Claude Desktop, Claude Code, another agent) can call them individually
instead of only running the fixed end-to-end pipeline.

This deliberately imports the exact same functions used by pipeline.py --
no duplicated logic. The MCP layer is just a thin adapter on top.

Run with: python -m src.mcp_server
"""
import asyncio
import json

from mcp.server.fastmcp import FastMCP

from src.confidence import compute_confidence
from src.crawler import crawl_domain as _crawl_domain
from src.extractor import build_llm_context, clean_page_text
from src.llm_client import extract_intel as _extract_intel
from src.search_fallback import find_company_leadership as _find_company_leadership
from src.search_fallback import find_linkedin_url as _find_linkedin_url

mcp = FastMCP("lead-enrichment-tools")


@mcp.tool()
async def crawl_domain(domain: str) -> dict:
    """Crawl a company domain: fetch the homepage and discover/fetch
    relevant subpages (about, team, contact, pricing, etc). Returns the
    list of pages fetched and which ones succeeded."""
    result = await _crawl_domain(domain)
    return {
        "domain": result.domain,
        "pages": [{"url": p.url, "ok": p.ok, "error": p.error} for p in result.pages],
        "successful_urls": result.successful_urls,
    }


@mcp.tool()
async def extract_clean_text(domain: str) -> str:
    """Crawl a domain and return clean, LLM-ready markdown text (HTML
    boilerplate, scripts, and nav/footer stripped out)."""
    crawl_result = await _crawl_domain(domain)
    return build_llm_context(crawl_result)


@mcp.tool()
async def extract_company_intel(domain: str) -> dict:
    """Full structured extraction for one domain: company overview, target
    audience, contact emails, and team members with roles/LinkedIn URLs.
    Uses Groq as primary LLM with Gemini as automatic fallback."""
    crawl_result = await _crawl_domain(domain)
    context_text = build_llm_context(crawl_result)
    llm_result = _extract_intel(context_text)

    if llm_result.intel is None:
        return {"domain": domain, "error": llm_result.error, "source": "failed"}

    intel = llm_result.intel
    confidence = compute_confidence(intel, pages_scraped=len(crawl_result.successful_urls))
    return {
        "domain": domain,
        "company_overview": intel.company_overview,
        "target_audience": intel.target_audience,
        "contact_emails": intel.contact_emails,
        "team_members": [m.model_dump() for m in intel.team_members],
        "confidence_score": confidence,
        "source": llm_result.source,
    }


@mcp.tool()
def find_linkedin(name: str, company: str) -> str:
    """Search for a person's LinkedIn profile URL given their name and
    company, using Tavily search. Returns empty string if not found."""
    return _find_linkedin_url(name, company) or ""


@mcp.tool()
def find_company_leadership(domain: str) -> list:
    """Search the open web (Tavily) for a company's founders/executives when
    the company's own site publishes no leadership page -- for domains like
    linear.app or notion.so where on-site scraping finds no team info at
    all. Returns a list of {name, role, linkedin_url} dicts."""
    return [m.model_dump() for m in _find_company_leadership(domain)]


if __name__ == "__main__":
    mcp.run()

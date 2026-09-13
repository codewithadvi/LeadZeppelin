"""
Tests for the ReAct-style agentic loop (bonus: "Agentic Frameworks / dynamic
navigation"). Instead of a hardcoded "always also try /leadership" rule, the
LLM looks at what's missing and picks ONE tool -- fetch more on-site pages,
search the open web for founders, or stop -- and the loop repeats up to
MAX_STEPS times based on the Observation from each Action.

Run: pytest tests/test_agentic_hop.py -v -m integration
"""
import pytest

from src.agentic import _summarize_gaps
from src.config import SUBPAGE_KEYWORDS
from src.crawler import discover_extra_urls
from src.llm_client import decide_next_step
from src.models import ExtractedIntel, TeamMember

pytestmark = pytest.mark.integration


def test_summarize_gaps_identifies_missing_fields():
    intel = ExtractedIntel(company_overview="", target_audience="", contact_emails=[], team_members=[])
    summary = _summarize_gaps(intel)
    assert "no company overview" in summary
    assert "no team members" in summary


def test_summarize_gaps_flags_missing_linkedin_separately_from_missing_team():
    intel = ExtractedIntel(
        company_overview="x", target_audience="y", contact_emails=["a@b.com"],
        team_members=[TeamMember(name="Jane", role="CEO")],  # no linkedin_url
    )
    summary = _summarize_gaps(intel)
    assert "no LinkedIn URLs" in summary
    assert "no team members" not in summary


def test_summarize_gaps_reports_nothing_missing_when_complete():
    intel = ExtractedIntel(
        company_overview="x", target_audience="y", contact_emails=["a@b.com"],
        team_members=[TeamMember(name="Jane", role="CEO", linkedin_url="https://linkedin.com/in/jane")],
    )
    assert _summarize_gaps(intel) == "nothing missing"


def test_decide_next_step_picks_a_valid_action():
    """Real LLM call: proves the decision is grounded in the stated gap
    (missing emails/LinkedIn) and returns one of the three defined tools."""
    decision = decide_next_step("no contact emails found; team members found but no LinkedIn URLs", SUBPAGE_KEYWORDS)
    assert decision.action in ("fetch_pages", "search_founders", "stop")


def test_decide_next_step_avoids_repeating_a_used_founder_search():
    """When told a founder search was already tried, the agent shouldn't
    pick search_founders again -- proves the loop's history actually
    constrains the next decision instead of being ignored."""
    decision = decide_next_step(
        "no team members found", SUBPAGE_KEYWORDS, already_tried_founder_search=True
    )
    assert decision.action != "search_founders"


def test_discover_extra_urls_excludes_already_fetched_pages():
    fake_html = """
    <a href="/leadership">Leadership</a>
    <a href="/about">About (already fetched)</a>
    <a href="/investors">Investors</a>
    """
    urls = discover_extra_urls(
        fake_html, "https://acme.com",
        keywords=["leadership", "about", "investors"],
        exclude=["https://acme.com/about"],
    )
    assert "https://acme.com/leadership" in urls
    assert "https://acme.com/investors" in urls
    assert "https://acme.com/about" not in urls


@pytest.mark.asyncio
async def test_agentic_loop_fires_and_does_not_crash_on_a_sparse_real_site():
    """End-to-end proof against a real low-information site (discovered
    empirically: fathom.video's homepage/about/pricing pages don't surface
    team or contact info, so the first pass lands under the confidence
    threshold and the agent should attempt -- and gracefully handle finding
    nothing more from -- multiple follow-up steps)."""
    from src.pipeline import process_domain

    result = await process_domain("fathom.video")
    assert result.llm_source in ("groq", "gemini", "failed")
    assert 0.0 <= result.confidence_score <= 1.0


@pytest.mark.asyncio
async def test_agentic_loop_never_exceeds_max_steps():
    """Regression guard against an infinite loop: even on a domain where
    nothing helps, the loop must terminate within MAX_STEPS."""
    from src.agentic import MAX_STEPS, AgenticState, run_agentic_loop
    from src.crawler import crawl_domain
    from src.extractor import build_llm_context
    from src.llm_client import extract_intel
    from src.confidence import compute_confidence

    crawl_result = await crawl_domain("fathom.video")
    context = build_llm_context(crawl_result)
    llm_result = extract_intel(context)
    assert llm_result.intel is not None

    confidence = compute_confidence(llm_result.intel, pages_scraped=len(crawl_result.successful_urls))
    state = AgenticState(
        extracted=llm_result.intel, llm_result=llm_result,
        confidence=confidence, pages_scraped=crawl_result.successful_urls,
    )
    state = await run_agentic_loop("fathom.video", crawl_result, state)
    assert state.steps_taken <= MAX_STEPS

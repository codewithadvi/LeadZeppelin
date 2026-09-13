"""
The ReAct-style agentic loop (bonus: "Agentic Frameworks / dynamic
navigation"). ReAct = Reason, then Act, then Observe the result, then
repeat -- this module is a small, explicit implementation of that pattern
rather than a black-box framework:

    Thought:      decide_next_step() looks at what's missing and picks ONE
                  tool to try next (fetch_pages / search_founders / stop)
    Action:       that tool actually runs (crawl more pages, or search the
                  open web for leadership)
    Observation:  re-extract structured intel from the new information and
                  recompute confidence
    (repeat)      up to MAX_STEPS times, or until the LLM says "stop"

This lives in its own module (not inline in pipeline.py) because it's a
genuinely separate concern -- pipeline.py orchestrates one straight-through
pass per domain; this is the part that loops and makes its own decisions.
"""
import logging
from dataclasses import dataclass, field
from typing import List

from src.confidence import compute_confidence
from src.config import SUBPAGE_KEYWORDS
from src.crawler import CrawlResult, discover_extra_urls, fetch_extra_pages
from src.extractor import build_llm_context
from src.llm_client import LLMResult, decide_next_step, extract_intel
from src.models import ExtractedIntel
from src.search_fallback import find_company_leadership

logger = logging.getLogger(__name__)

MAX_STEPS = 3
CONFIDENCE_GOOD_ENOUGH = 0.6


@dataclass
class AgenticState:
    extracted: ExtractedIntel
    llm_result: LLMResult
    confidence: float
    pages_scraped: List[str]
    steps_taken: int = 0
    trace: List[str] = field(default_factory=list)  # human-readable Thought/Action/Observation log


def _summarize_gaps(intel: ExtractedIntel) -> str:
    """Plain-English summary of what's missing, handed to the LLM so its
    next-step decision is grounded in the actual gap rather than guessing."""
    gaps = []
    if not intel.company_overview:
        gaps.append("no company overview found")
    if not intel.target_audience:
        gaps.append("no target audience found")
    if not intel.contact_emails:
        gaps.append("no contact emails found")
    if not intel.team_members:
        gaps.append("no team members found")
    elif not any(m.linkedin_url for m in intel.team_members):
        gaps.append("team members found but no LinkedIn URLs")
    return "; ".join(gaps) if gaps else "nothing missing"


async def run_agentic_loop(domain: str, crawl_result: CrawlResult, state: AgenticState) -> AgenticState:
    """Runs up to MAX_STEPS Thought->Action->Observation iterations,
    stopping early once confidence is good enough or the LLM decides
    nothing more will help. Mutates and returns `state`."""
    tried_keywords: List[str] = list(SUBPAGE_KEYWORDS)
    tried_founder_search = False

    while state.confidence <= CONFIDENCE_GOOD_ENOUGH and state.steps_taken < MAX_STEPS:
        state.steps_taken += 1
        gap_summary = _summarize_gaps(state.extracted)

        # --- Thought ---
        decision = decide_next_step(gap_summary, tried_keywords, tried_founder_search)
        state.trace.append(f"Thought[{state.steps_taken}]: {decision.reason} -> action={decision.action}")
        logger.info("Agentic step %d for %s: action=%s keywords=%s reason=%s",
                    state.steps_taken, domain, decision.action, decision.additional_keywords, decision.reason)

        if decision.action == "stop":
            break

        # --- Action ---
        if decision.action == "fetch_pages" and decision.additional_keywords:
            tried_keywords.extend(decision.additional_keywords)
            homepage_html = crawl_result.pages[0].html
            extra_urls = discover_extra_urls(
                homepage_html, f"https://{domain}", decision.additional_keywords, exclude=state.pages_scraped
            )
            if not extra_urls:
                state.trace.append(f"Observation[{state.steps_taken}]: no pages matched {decision.additional_keywords}")
                continue

            extra_pages = await fetch_extra_pages(extra_urls)
            crawl_result.pages.extend(extra_pages)
            state.pages_scraped = crawl_result.successful_urls

            retry_context = build_llm_context(crawl_result)
            retry_result = extract_intel(retry_context)

            # --- Observation ---
            if retry_result.intel is not None:
                retry_confidence = compute_confidence(retry_result.intel, pages_scraped=len(state.pages_scraped))
                state.trace.append(f"Observation[{state.steps_taken}]: fetched {len(extra_pages)} page(s), "
                                    f"confidence {state.confidence:.2f} -> {retry_confidence:.2f}")
                if retry_confidence > state.confidence:
                    state.extracted = retry_result.intel
                    state.confidence = retry_confidence
                    state.llm_result = retry_result

        elif decision.action == "search_founders":
            tried_founder_search = True
            found_members = find_company_leadership(domain)
            if not found_members:
                state.trace.append(f"Observation[{state.steps_taken}]: open-web founder search found nothing")
                continue

            merged = state.extracted.team_members + [
                m for m in found_members
                if m.name not in {existing.name for existing in state.extracted.team_members}
            ]
            state.extracted.team_members = merged
            new_confidence = compute_confidence(state.extracted, pages_scraped=len(state.pages_scraped))
            state.trace.append(f"Observation[{state.steps_taken}]: found {len(found_members)} leader(s) via web "
                                f"search, confidence {state.confidence:.2f} -> {new_confidence:.2f}")
            state.confidence = new_confidence

        else:
            break  # fetch_pages chosen with no keywords, or an unrecognized action -- stop rather than loop forever

    return state

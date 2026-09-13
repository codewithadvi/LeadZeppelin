"""
Orchestrates a single domain through the full flow:
crawl -> extract clean text -> LLM structured extraction -> confidence score
-> agentic ReAct loop (src/agentic.py) -> per-person LinkedIn fallback -> cost log.

Every domain is wrapped in a top-level try/except so one broken site (DNS
failure, total bot-block, malformed response) can never take down a batch
run over multiple domains -- it just produces a `failed` record and we move on.
"""
import logging
from typing import List

from src.agentic import AgenticState, run_agentic_loop
from src.confidence import compute_confidence
from src.cost_log import CostEntry, append_cost_entry
from src.crawler import crawl_domain
from src.extractor import build_llm_context
from src.llm_client import extract_intel
from src.models import CompanyIntel
from src.search_fallback import find_linkedin_url

logger = logging.getLogger(__name__)


async def process_domain(domain: str) -> CompanyIntel:
    try:
        crawl_result = await crawl_domain(domain)
        pages_scraped = crawl_result.successful_urls

        if not pages_scraped:
            return CompanyIntel(
                domain=domain,
                llm_source="failed",
                error="all pages failed to fetch (timeout/404/bot-block)",
                pages_scraped=[],
            )

        context_text = build_llm_context(crawl_result)
        llm_result = extract_intel(context_text)

        if llm_result.source != "failed" and llm_result.prompt_tokens:
            append_cost_entry(CostEntry(
                domain=domain,
                llm_source=llm_result.source,
                prompt_tokens=llm_result.prompt_tokens,
                completion_tokens=llm_result.completion_tokens,
                latency_seconds=llm_result.latency_seconds,
            ))

        if llm_result.intel is None:
            return CompanyIntel(
                domain=domain,
                llm_source="failed",
                error=llm_result.error or "LLM extraction failed",
                pages_scraped=pages_scraped,
            )

        confidence = compute_confidence(llm_result.intel, pages_scraped=len(pages_scraped))

        # ReAct-style agentic loop (bonus): Thought -> Action -> Observation,
        # up to 3 rounds, choosing between fetching more on-site pages or
        # falling back to an open-web founder search. See src/agentic.py.
        state = AgenticState(
            extracted=llm_result.intel, llm_result=llm_result,
            confidence=confidence, pages_scraped=pages_scraped,
        )
        state = await run_agentic_loop(domain, crawl_result, state)
        for line in state.trace:
            logger.info("[%s] %s", domain, line)

        extracted = state.extracted
        pages_scraped = state.pages_scraped
        llm_result = state.llm_result

        # Bonus: fill in missing LinkedIn URLs via search for anyone we found
        # a name+role for but no on-page profile link.
        for member in extracted.team_members:
            if not member.linkedin_url:
                member.linkedin_url = find_linkedin_url(member.name, domain)

        confidence = compute_confidence(extracted, pages_scraped=len(pages_scraped))

        return CompanyIntel(
            domain=domain,
            company_overview=extracted.company_overview,
            target_audience=extracted.target_audience,
            contact_emails=extracted.contact_emails,
            team_members=extracted.team_members,
            confidence_score=confidence,
            llm_source=llm_result.source,
            pages_scraped=pages_scraped,
        )

    except Exception as exc:  # noqa: BLE001 - final safety net, one domain must never kill the batch
        logger.exception("Unhandled error processing domain %s", domain)
        return CompanyIntel(domain=domain, llm_source="failed", error=f"{type(exc).__name__}: {exc}")


async def process_domains(domains: List[str]) -> List[CompanyIntel]:
    results = []
    for domain in domains:
        logger.info("Processing %s", domain)
        result = await process_domain(domain)
        results.append(result)
    return results

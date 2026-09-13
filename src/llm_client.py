"""
Structured extraction with automatic fallback: Groq (fast, free-tier Llama
3.3 70B) is primary; Gemini 2.0 Flash is the backup if Groq errors, rate
limits, or times out.

Why Instructor for Groq: raw LLM calls return text, so you're stuck hoping
the model formatted JSON correctly. Instructor converts our Pydantic model
into a tool-calling schema, so the model fills in structured arguments
(something LLMs are heavily trained to do reliably) instead of "writing
JSON". It also validates the response against the Pydantic model and
auto-retries with a corrective message if validation fails -- for free.

Gemini doesn't need Instructor: it natively supports response_schema
(JSON-schema-constrained decoding), so we reuse the exact same Pydantic
model via `.model_json_schema()` -- one schema, two backends, no drift.
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

import instructor
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)
from src.models import ExtractedIntel, NextStepDecision

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a precise B2B research analyst extracting structured company \
intelligence from scraped website text.

Rules:
- Only extract information that is explicitly present in the provided text.
- Never invent names, emails, titles, or URLs that are not present.
- If a field cannot be found, leave it empty (empty string / empty list) rather than guessing.
- For contact_emails: only include emails that are plausible real contact points for this specific \
company -- typically on the company's own domain, or well-known role aliases (support@, sales@, \
contact@, careers@). SKIP emails that look like placeholder/example text from a form field, code \
sample, or documentation snippet (e.g. jane.smith@example.com, kevin@encom.com, test@test.com, \
your.email@company.com) -- these are filler text, not real contact points, even though they appear \
verbatim in the scraped text.
- company_overview must be exactly 2 sentences.
- target_audience should describe the ideal customer profile concretely, e.g. \
"Developers building backend APIs", not vague terms like "everyone".
- For team_members, only include people who work AT the company being researched (its own founders, \
executives, leadership). Do NOT include people quoted in customer testimonials, case studies, or \
partner mentions -- e.g. if the page shows a quote like "This tool is great" - Jane Doe, CEO of \
SomeOtherCompany, that is a customer testimonial, not one of this company's team members, even \
though a name and role are clearly present. A strong signal: if someone's stated role mentions a \
DIFFERENT company than the one you're researching, they are not a team member of this company.
- Only include a team_members entry if you have a clear name AND role/title mentioned together.
- linkedin_url should only be filled if an actual linkedin.com URL for that person appears in the text.
"""


@dataclass
class LLMResult:
    intel: Optional[ExtractedIntel]
    source: Literal["groq", "gemini", "failed"]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    error: str = ""


@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(2))
def _call_groq(context_text: str) -> LLMResult:
    client = instructor.from_groq(Groq(api_key=GROQ_API_KEY), mode=instructor.Mode.TOOLS)
    start = time.time()
    result, completion = client.chat.completions.create_with_completion(
        model=GROQ_MODEL,
        response_model=ExtractedIntel,
        max_retries=2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context_text},
        ],
    )
    usage = getattr(completion, "usage", None)
    return LLMResult(
        intel=result,
        source="groq",
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_seconds=time.time() - start,
    )


@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(2))
def _call_gemini(context_text: str) -> LLMResult:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    schema = ExtractedIntel.model_json_schema()

    model = genai.GenerativeModel(
        GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": schema,
        },
    )
    start = time.time()
    response = model.generate_content(context_text)
    data = json.loads(response.text)
    intel = ExtractedIntel.model_validate(data)

    usage = getattr(response, "usage_metadata", None)
    return LLMResult(
        intel=intel,
        source="gemini",
        prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
        completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        latency_seconds=time.time() - start,
    )


DECISION_PROMPT = """You are the reasoning step of a ReAct-style web-scraping agent, deciding what \
to do next before giving up on a company's data.

You'll be shown what's been tried so far (pages fetched, searches run) and what's still missing \
(e.g. no team members, no LinkedIn URLs, no contact emails). Pick exactly ONE action:

- "fetch_pages": try more on-site pages, IF you have a concrete, plausible guess at URL keywords \
that haven't been tried yet (e.g. missing leadership -> "leadership", "founders", "investors", \
"management"; missing contact info -> "support", "help", "contact-sales"). Don't repeat keywords \
already tried.
- "search_founders": use when team members are still missing AND on-site fetch_pages attempts have \
already failed to find them (or you have no new keyword ideas left) -- this searches the open web \
instead of the company's own site, for cases where the company simply doesn't publish a leadership \
page.
- "stop": when nothing listed above is likely to help, or everything needed has already been found.

Don't choose an action just to keep going -- only continue if you have a genuinely plausible reason \
this specific action will fill a specific gap.
"""


def decide_next_step(context_summary: str, already_tried_keywords: list, already_tried_founder_search: bool = False) -> NextStepDecision:
    """The Thought+Action step of the ReAct loop: instead of us hardcoding a
    fixed sequence of fallbacks, the LLM looks at what's missing and what's
    already been tried, then picks ONE of three tools. Failure here is
    non-fatal -- the loop just stops and keeps the best result found so far."""
    if not GROQ_API_KEY:
        return NextStepDecision(action="stop", reason="no LLM key configured")

    try:
        client = instructor.from_groq(Groq(api_key=GROQ_API_KEY), mode=instructor.Mode.TOOLS)
        tried_summary = f"Already tried these URL keywords: {already_tried_keywords}"
        if already_tried_founder_search:
            tried_summary += "\nAlready tried an open-web founder search -- do not choose search_founders again."

        return client.chat.completions.create(
            model=GROQ_MODEL,
            response_model=NextStepDecision,
            max_retries=1,
            messages=[
                {"role": "system", "content": DECISION_PROMPT},
                {"role": "user", "content": f"{tried_summary}\n\nCurrent extraction state:\n{context_summary}"},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agentic next-step decision failed, stopping the loop: %s", exc)
        return NextStepDecision(action="stop", reason=f"decision call failed: {exc}")


def extract_intel(context_text: str) -> LLMResult:
    """Try Groq first; on any failure, fall back to Gemini; if both fail,
    return a `failed` LLMResult so the pipeline can still emit a record."""
    if not context_text.strip():
        return LLMResult(intel=None, source="failed", error="no scrapeable content")

    if GROQ_API_KEY:
        try:
            return _call_groq(context_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Groq extraction failed, falling back to Gemini: %s", exc)

    if GEMINI_API_KEY:
        try:
            return _call_gemini(context_text)
        except Exception as exc:  # noqa: BLE001
            logger.error("Gemini extraction also failed: %s", exc)
            return LLMResult(intel=None, source="failed", error=str(exc))

    return LLMResult(intel=None, source="failed", error="no LLM API keys configured")

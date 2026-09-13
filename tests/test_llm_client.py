"""
Integration tests for structured LLM extraction -- these make real API
calls, so they require GROQ_API_KEY (and optionally GEMINI_API_KEY) set in
.env. They prove the Instructor + Pydantic structured-output contract
actually holds against a live model, not just against a mock.

Run: pytest tests/test_llm_client.py -v -m integration
"""
import os

import pytest

from src.llm_client import extract_intel

pytestmark = pytest.mark.integration

SAMPLE_TEXT = """
--- PAGE: https://acme.com/ ---
# Acme Corp
Acme builds developer tools for backend teams. Our platform helps engineers
ship APIs faster with zero configuration.

--- PAGE: https://acme.com/about ---
## Our Team
Jane Doe, CEO & Co-founder — https://linkedin.com/in/janedoe
John Smith, CTO — https://linkedin.com/in/johnsmith

Contact us at contact@acme.com or sales@acme.com.
"""


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_extract_intel_returns_valid_structured_data():
    result = extract_intel(SAMPLE_TEXT)
    assert result.source in ("groq", "gemini")
    assert result.intel is not None
    assert len(result.intel.company_overview) > 0
    assert "contact@acme.com" in result.intel.contact_emails
    assert any(m.name == "Jane Doe" for m in result.intel.team_members)


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_extract_intel_does_not_hallucinate_on_empty_input():
    result = extract_intel("")
    assert result.source == "failed"
    assert result.intel is None


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_extract_intel_picks_up_linkedin_urls_from_text():
    result = extract_intel(SAMPLE_TEXT)
    linkedin_urls = [m.linkedin_url for m in result.intel.team_members if m.linkedin_url]
    assert any("linkedin.com/in/janedoe" in url for url in linkedin_urls)


TESTIMONIAL_TEXT = """
--- PAGE: https://acme.com/ ---
# Acme Corp
Acme builds developer tools for backend teams.

## What our customers say
"Acme completely changed how our team ships code." — Sarah Lee, CEO, OtherCorp
"The best tool we've adopted this year." — Mike Chen, CTO, ThirdCo

Contact us at contact@acme.com.
"""


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_extract_intel_does_not_confuse_customer_testimonials_with_team_members():
    """Regression test for a real bug found scraping linear.app: customer
    testimonial quotes ("Patrick Collison, CEO, Stripe" praising the
    product) were extracted as Linear's own team members, because the name
    + role pattern looked identical to a real team bio. The names/roles
    read correctly -- they were just attributed to the wrong company."""
    result = extract_intel(TESTIMONIAL_TEXT)
    assert result.intel is not None
    names = [m.name for m in result.intel.team_members]
    assert "Sarah Lee" not in names
    assert "Mike Chen" not in names

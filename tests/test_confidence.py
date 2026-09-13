"""
Pure unit tests for the confidence scorer -- no network, no API keys.
Run: pytest tests/test_confidence.py -v
"""
from src.confidence import compute_confidence
from src.models import ExtractedIntel, TeamMember


def test_empty_extraction_scores_zero():
    intel = ExtractedIntel(company_overview="", target_audience="", contact_emails=[], team_members=[])
    assert compute_confidence(intel, pages_scraped=3) == 0.0


def test_full_extraction_scores_near_one():
    intel = ExtractedIntel(
        company_overview="This company builds developer tools. It focuses on APIs.",
        target_audience="Backend developers",
        contact_emails=["contact@example.com"],
        team_members=[TeamMember(name="Jane Doe", role="CEO", linkedin_url="https://linkedin.com/in/janedoe")],
    )
    assert compute_confidence(intel, pages_scraped=3) == 1.0


def test_partial_extraction_scores_between():
    intel = ExtractedIntel(
        company_overview="This company builds developer tools. It focuses on APIs.",
        target_audience="",
        contact_emails=[],
        team_members=[],
    )
    score = compute_confidence(intel, pages_scraped=3)
    assert 0.0 < score < 1.0
    assert score == 0.25  # only the overview weight


def test_low_page_coverage_applies_penalty():
    intel = ExtractedIntel(
        company_overview="This company builds developer tools. It focuses on APIs.",
        target_audience="Developers",
        contact_emails=["contact@example.com"],
        team_members=[TeamMember(name="Jane Doe", role="CEO")],
    )
    full_coverage = compute_confidence(intel, pages_scraped=3)
    low_coverage = compute_confidence(intel, pages_scraped=1)
    assert low_coverage < full_coverage

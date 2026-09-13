"""
Unit tests for the HTML report generator -- no network needed.
Run: pytest tests/test_report.py -v
"""
from src.models import CompanyIntel, TeamMember
from src.report import generate_html_report


def test_report_renders_successful_domain_with_all_fields():
    intel = CompanyIntel(
        domain="acme.com",
        company_overview="Acme builds developer tools.",
        target_audience="Backend developers",
        contact_emails=["contact@acme.com"],
        team_members=[TeamMember(name="Jane Doe", role="CEO", linkedin_url="https://linkedin.com/in/janedoe")],
        confidence_score=0.9,
        llm_source="groq",
        pages_scraped=["https://acme.com"],
    )
    html = generate_html_report([intel])
    assert "acme.com" in html
    assert "Jane Doe" in html
    assert "contact@acme.com" in html
    assert "linkedin.com/in/janedoe" in html
    assert "90% confidence" in html


def test_report_renders_failed_domain_distinctly():
    intel = CompanyIntel(domain="deadsite.com", llm_source="failed", error="all pages failed to fetch")
    html = generate_html_report([intel])
    assert "deadsite.com" in html
    assert "FAILED" in html
    assert "all pages failed to fetch" in html
    assert 'class="card failed"' in html


def test_report_handles_empty_results_list():
    html = generate_html_report([])
    assert "0/0 domains" in html

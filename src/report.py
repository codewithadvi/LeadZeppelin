"""
Generates a human-readable HTML report from the CompanyIntel output --
the same JSON, but something you'd actually hand to a salesperson instead
of asking them to read raw JSON.

Deliberately HTML rather than a PDF library: weasyprint/wkhtmltopdf require
system-level GTK/Qt dependencies that are painful to install on Windows for
a take-home assignment. A generated HTML file opens in any browser and
"Print to PDF" (Ctrl+P) is a one-click way to get a PDF from it -- same
result, zero fragile dependencies.
"""
from typing import List

from src.models import CompanyIntel

STYLE = """
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 900px;
         margin: 40px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 1.6rem; margin-bottom: 4px; }
  .subtitle { color: #666; margin-bottom: 32px; }
  .card { border: 1px solid #e0e0e0; border-radius: 10px; padding: 24px; margin-bottom: 20px; }
  .card.failed { border-color: #f3c1c1; background: #fff8f8; }
  .domain-row { display: flex; justify-content: space-between; align-items: baseline; }
  .domain { font-size: 1.25rem; font-weight: 600; }
  .confidence { font-size: 0.9rem; font-weight: 600; padding: 4px 10px; border-radius: 999px; }
  .conf-high { background: #dcfce7; color: #166534; }
  .conf-mid { background: #fef9c3; color: #854d0e; }
  .conf-low { background: #fee2e2; color: #991b1b; }
  .overview { margin: 14px 0; line-height: 1.5; }
  .section-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
                    color: #888; margin-top: 16px; margin-bottom: 6px; }
  .team-member { padding: 6px 0; }
  .team-member a { color: #2563eb; text-decoration: none; }
  .emails span { background: #f1f5f9; padding: 2px 8px; border-radius: 6px; margin-right: 6px;
                 font-family: monospace; font-size: 0.9rem; }
  .error-text { color: #991b1b; font-family: monospace; font-size: 0.9rem; }
  .pages-scraped { font-size: 0.8rem; color: #999; margin-top: 16px; }
</style>
"""


def _confidence_class(score: float) -> str:
    if score >= 0.7:
        return "conf-high"
    if score >= 0.4:
        return "conf-mid"
    return "conf-low"


def _render_card(intel: CompanyIntel) -> str:
    if intel.llm_source == "failed":
        return f"""
        <div class="card failed">
          <div class="domain-row">
            <span class="domain">{intel.domain}</span>
            <span class="confidence conf-low">FAILED</span>
          </div>
          <p class="error-text">{intel.error or 'Unknown error'}</p>
        </div>
        """

    team_html = "".join(
        f'<div class="team-member">{m.name} &mdash; {m.role}'
        + (f' &middot; <a href="{m.linkedin_url}">LinkedIn</a>' if m.linkedin_url else "")
        + "</div>"
        for m in intel.team_members
    ) or '<div class="team-member" style="color:#999">None found</div>'

    emails_html = "".join(f"<span>{e}</span>" for e in intel.contact_emails) or '<span style="color:#999">None found</span>'

    return f"""
    <div class="card">
      <div class="domain-row">
        <span class="domain">{intel.domain}</span>
        <span class="confidence {_confidence_class(intel.confidence_score)}">
          {intel.confidence_score:.0%} confidence &middot; {intel.llm_source}
        </span>
      </div>
      <p class="overview">{intel.company_overview}</p>

      <div class="section-label">Target Audience</div>
      <div>{intel.target_audience}</div>

      <div class="section-label">Contact Emails</div>
      <div class="emails">{emails_html}</div>

      <div class="section-label">Team</div>
      {team_html}

      <div class="pages-scraped">Scraped {len(intel.pages_scraped)} pages: {', '.join(intel.pages_scraped)}</div>
    </div>
    """


def generate_html_report(results: List[CompanyIntel]) -> str:
    cards = "".join(_render_card(r) for r in results)
    succeeded = sum(1 for r in results if r.llm_source != "failed")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Lead Enrichment Report</title>{STYLE}</head>
<body>
  <h1>Lead Enrichment Report</h1>
  <p class="subtitle">{succeeded}/{len(results)} domains enriched successfully</p>
  {cards}
</body></html>
"""


def write_report(results: List[CompanyIntel], path: str = "report.html") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(generate_html_report(results))

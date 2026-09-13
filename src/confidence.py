"""
Confidence scoring is deliberately NOT delegated to the LLM. Asking a model
"rate your confidence 0-1" produces an ungrounded number with no way to
audit why it picked that value. Instead we compute a weighted score from
what was actually found -- fully explainable and independently testable.
"""
from src.models import ExtractedIntel

WEIGHTS = {
    "overview": 0.25,
    "audience": 0.15,
    "emails": 0.20,
    "team": 0.25,
    "linkedin": 0.15,
}


def compute_confidence(intel: ExtractedIntel, pages_scraped: int) -> float:
    score = 0.0

    if intel.company_overview and len(intel.company_overview.strip()) > 20:
        score += WEIGHTS["overview"]

    if intel.target_audience and len(intel.target_audience.strip()) > 5:
        score += WEIGHTS["audience"]

    if intel.contact_emails:
        score += WEIGHTS["emails"]

    if intel.team_members:
        score += WEIGHTS["team"]

    if any(m.linkedin_url for m in intel.team_members):
        score += WEIGHTS["linkedin"]

    # Small penalty if we barely scraped anything -- low page coverage means
    # even a "complete-looking" extraction may be missing context.
    if pages_scraped <= 1:
        score *= 0.7

    return round(min(score, 1.0), 2)

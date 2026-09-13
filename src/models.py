"""
Pydantic schemas shared by every stage of the pipeline: the LLM extraction
step, the crawler's output, and the final JSON we write to disk.

Keeping these in one file means the LLM call, the confidence scorer, and the
MCP tool layer all agree on exactly one shape -- no silent drift between them.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TeamMember(BaseModel):
    name: str = Field(description="Full name of the leadership/team member")
    role: str = Field(description="Their job title/role, e.g. 'CEO & Co-founder'")
    linkedin_url: Optional[str] = Field(
        default=None, description="LinkedIn profile URL if present in the page content"
    )


class ExtractedIntel(BaseModel):
    """What we ask the LLM to fill in. Deliberately does NOT include the
    deterministic fields (confidence_score, source, pages_scraped) -- those
    are computed in Python, not guessed by the model."""

    company_overview: str = Field(
        description="A concise 2-sentence summary of what the company does"
    )
    target_audience: str = Field(
        description="Who the product is built for, e.g. 'Developers building backend APIs'"
    )
    contact_emails: List[str] = Field(
        default_factory=list,
        description="Generic/public emails found on the site, e.g. contact@, sales@, support@",
    )
    team_members: List[TeamMember] = Field(default_factory=list)


class LeadershipSearchResult(BaseModel):
    """Wraps a bare List[TeamMember] so Instructor has a concrete response
    model to bind the Groq tool-call schema to (structured extraction needs
    a BaseModel, not a bare list)."""

    team_members: List[TeamMember] = Field(default_factory=list)


class NextStepDecision(BaseModel):
    """The Thought+Action step of the ReAct loop (see src/agentic.py):
    given what's still missing, the LLM picks ONE of three tools rather than
    us hardcoding a fixed sequence -- this is the actual tool-calling
    decision, re-run after every Observation until it says 'stop' or a step
    cap is hit."""

    action: Literal["fetch_pages", "search_founders", "stop"] = Field(
        description="fetch_pages: try more on-site pages matching new keywords. "
        "search_founders: the site itself likely has no leadership page -- search the open web instead. "
        "stop: nothing more is likely to help, or everything needed was already found."
    )
    additional_keywords: List[str] = Field(
        default_factory=list,
        description="URL path keywords to search for, e.g. ['leadership', 'founders', 'investors']. "
        "Only meaningful when action is 'fetch_pages'.",
    )
    reason: str = Field(default="", description="One sentence explaining the decision")


class CompanyIntel(BaseModel):
    """The final record written to output.json -- one per domain."""

    domain: str
    company_overview: str = ""
    target_audience: str = ""
    contact_emails: List[str] = Field(default_factory=list)
    team_members: List[TeamMember] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.0)
    llm_source: Literal["groq", "gemini", "failed"] = "failed"
    pages_scraped: List[str] = Field(default_factory=list)
    error: Optional[str] = None

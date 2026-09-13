"""
Single place every other module reads settings from. Nothing else in the
codebase should call os.getenv directly -- that way, if we ever need to add
a new key or change a default, there's exactly one place to look.
"""
import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

MAX_SUBPAGES = int(os.getenv("MAX_SUBPAGES", "5"))
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "15000"))
MAX_CHARS_PER_PAGE = int(os.getenv("MAX_CHARS_PER_PAGE", "4000"))

SUBPAGE_KEYWORDS = [
    "about", "team", "company", "contact", "pricing",
    "leadership", "careers", "people",
]

# Rough per-1M-token pricing (paid tier) used only for the cost-estimate log
# even though we run on free tiers -- shows what this would cost at scale.
GROQ_PRICE_PER_M_INPUT = 0.59
GROQ_PRICE_PER_M_OUTPUT = 0.79
GEMINI_PRICE_PER_M_INPUT = 0.10
GEMINI_PRICE_PER_M_OUTPUT = 0.40

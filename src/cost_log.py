"""
Bonus feature: track token usage and estimated cost per domain. We run on
free tiers, so this logs what the run *would* cost at each provider's paid
rate -- demonstrates cost-awareness even when actual spend is $0.
"""
import csv
import logging
import os
from dataclasses import dataclass

from src.config import (
    GEMINI_PRICE_PER_M_INPUT,
    GEMINI_PRICE_PER_M_OUTPUT,
    GROQ_PRICE_PER_M_INPUT,
    GROQ_PRICE_PER_M_OUTPUT,
)

logger = logging.getLogger(__name__)

CSV_PATH = "cost_log.csv"
FIELDNAMES = ["domain", "llm_source", "prompt_tokens", "completion_tokens",
              "latency_seconds", "estimated_cost_usd"]


@dataclass
class CostEntry:
    domain: str
    llm_source: str
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float

    @property
    def estimated_cost_usd(self) -> float:
        if self.llm_source == "groq":
            in_price, out_price = GROQ_PRICE_PER_M_INPUT, GROQ_PRICE_PER_M_OUTPUT
        elif self.llm_source == "gemini":
            in_price, out_price = GEMINI_PRICE_PER_M_INPUT, GEMINI_PRICE_PER_M_OUTPUT
        else:
            return 0.0
        cost = (self.prompt_tokens / 1_000_000) * in_price
        cost += (self.completion_tokens / 1_000_000) * out_price
        return round(cost, 6)


def append_cost_entry(entry: CostEntry) -> None:
    file_exists = os.path.isfile(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "domain": entry.domain,
            "llm_source": entry.llm_source,
            "prompt_tokens": entry.prompt_tokens,
            "completion_tokens": entry.completion_tokens,
            "latency_seconds": round(entry.latency_seconds, 2),
            "estimated_cost_usd": entry.estimated_cost_usd,
        })

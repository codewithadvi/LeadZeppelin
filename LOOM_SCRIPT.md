# Loom walkthrough script (target: 2:30–3:00)

The assignment caps the video at 2-3 minutes, so this script is tight by
design — it hits every rubric line without padding. Read the **Script**
section on camera; use the **Reference tables** below it only if you want
to go deeper on a specific file or field a question afterward.

---

## Script (say this, roughly — don't read word-for-word, sound natural)

### 0:00–0:20 — What this is (20s)

> "This is an autonomous lead enrichment agent. You give it a list of
> company domains, it crawls their public site with a real headless
> browser, cleans the HTML down to just the useful text, and uses an LLM
> with structured outputs to pull out a company overview, target audience,
> contact emails, and team members with LinkedIn URLs — each with a
> confidence score. It also ships as an MCP server exposing the same tools."

### 0:20–1:00 — Code structure, one breath each (40s)

Share your screen on the `src/` folder and go top to bottom, one sentence
per file:

> "`models.py` is the contract — the Pydantic schemas every stage agrees
> on. `crawler.py` uses Playwright to render JS-heavy sites and discover
> subpages like /about and /team. `extractor.py` strips that down to clean
> markdown with trafilatura, plus a regex pass for links and emails.
> `llm_client.py` does structured extraction with Groq and Instructor,
> falling back to Gemini if Groq fails. `confidence.py` computes a
> deterministic completeness score — not an LLM guess. `agentic.py` is the
> bonus ReAct loop — ask, act, observe, repeat — that decides whether to
> fetch more pages or search the open web when confidence is low.
> `search_fallback.py` and `cost_log.py` are the Tavily search and
> cost-tracking bonuses. `pipeline.py` wires it all together with
> try/except at three levels so one broken site never crashes a batch.
> `mcp_server.py` exposes the same building blocks as MCP tools."

### 1:00–1:20 — Run the tests live (20s)

Run this in the terminal, let it start, narrate over it:

```bash
pytest tests/ -v
```

> "32 tests — pure logic ones run instantly with no network, the rest hit
> real sites and real LLM calls. I'm not going to wait for all of them on
> camera, but here's them passing." *(cut to the PASSED summary line)*

### 1:20–2:20 — The real bugs (this is your strongest material — 60s)

Pick 2, max 3, of these — say them like a detective story, not a bullet list:

> "A few things I actually hit running this against real sites, not toy
> examples. First: Playwright's `networkidle` wait condition never fires on
> postman.com, because it has persistent analytics connections keeping the
> network 'busy' forever — every fetch just timed out even though the page
> had rendered fine. Switched to `domcontentloaded` plus a short fixed
> wait, fixed it.
>
> Second, and this one's subtler: when I ran this against stripe.com, the
> extracted emails were garbage — `jane.smith@example.com`, stuff pulled
> straight out of Next.js's embedded JSON blob full of documentation code
> samples. Fixed by stripping script tags before running any regex.
>
> Third: on linear.app, the LLM extracted Stripe's CEO and Figma's CEO as
> Linear's own team members — because they were quoted in customer
> testimonials on Linear's homepage. The names and roles were read
> correctly, just attributed to the wrong company. Fixed with an explicit
> prompt rule."

### 2:20–2:50 — Run it live, show the output (30s)

```bash
python -m src.main --domains postman.com supabase.com vapi.ai --report
```

> "That's writing output.json, a cost log, and a human-readable HTML
> report." *(open `report.html` in a browser, scroll through it for 5-10s)*

### 2:50–3:00 — Close (10s)

> "All the design decisions and every bug I found are documented in the
> README, including a couple I hit today running it against companies
> outside the original three. And yes — I'm comfortable with the 40%
> manual ops split."

---

## Reference: file-by-file cheat sheet (for Q&A, not for the video script)

| File | What it does | Library/tool | Why this one |
|---|---|---|---|
| `models.py` | Pydantic schemas — the shared contract | Pydantic | Type-safe, validates automatically, one source of truth |
| `config.py` | Centralized env vars | `python-dotenv` | One place to look, nothing scattered |
| `crawler.py` | Fetch homepage + discover/fetch subpages | Playwright | Renders JS (Next.js/React); `requests` returns an empty shell |
| `extractor.py` | HTML → clean markdown + regex link/email recovery | trafilatura + `re` | Strips boilerplate for token savings; regex catches what trafilatura drops |
| `confidence.py` | Deterministic 0–1 completeness score | pure Python | Auditable — traces to a reason, not an LLM guess |
| `llm_client.py` | Structured extraction, Groq→Gemini fallback, ReAct decision step | Groq + Instructor + Gemini | Instructor forces valid Pydantic output via tool-calling, not text parsing |
| `agentic.py` | The ReAct loop — Thought/Action/Observation, ≤3 steps | Groq (via llm_client) | Agent picks its own next tool instead of a hardcoded fallback |
| `search_fallback.py` | LinkedIn search + broad founder search | Tavily + Instructor | Built for LLM-agent use; free tier; clean JSON not raw SERP HTML |
| `cost_log.py` | Per-domain token/cost logging | — | Shows cost awareness even on free tiers |
| `report.py` | JSON → readable HTML report | — (pure string templating) | Avoids `weasyprint`/`wkhtmltopdf`'s GTK/Qt install pain on Windows |
| `pipeline.py` | Orchestrates one domain end to end | — | 3-layer try/except: page, LLM call, whole domain |
| `main.py` | CLI entrypoint | `argparse` | `--domains`, `--output`, `--report` flags |
| `mcp_server.py` | Exposes the same functions as MCP tools | `mcp` (FastMCP) | Reusable by any MCP client, zero duplicated logic |

## All the real bugs found (pick your favorites for the video)

1. **`networkidle` never fires on postman.com** — persistent analytics connections → switched to `domcontentloaded` + fixed delay.
2. **Stale Groq model name** — `llama-3.3-70b-versatile` gone → queried `client.models.list()` live, switched models.
3. **`httpx`/`groq` version conflict** — `httpx==0.28` dropped a kwarg the pinned `groq` SDK needed → pinned `httpx==0.27.2`.
4. **trafilatura drops hrefs** — keeps anchor text, not the URL → separate regex pass on raw HTML.
5. **Tavily subdomain miss** — `in.linkedin.com` not matched by a `www.linkedin.com`-only regex → widened the pattern.
6. **Script/JSON blobs leaking into emails** — stripe.com's Next.js JSON blob leaked doc-sample emails and a raw `>` escape artifact → strip `<script>`/`<style>` before regex.
7. **Confidence boundary bug** — empty team + everything else found = exactly 0.60, and `< 0.6` never fired → changed to `<= 0.6`.
8. **Customer testimonials read as team members** — linear.app's homepage quotes from other companies' CEOs → explicit prompt rule.
9. **Placeholder email past the blocklist** — `kevin@encom.com` → taught the LLM to reason about plausibility instead of growing a blocklist forever.
10. **Founder-search schema mismatch** — model said `"title"` instead of `"role"`, only 1 retry wasn't enough for self-correction → bumped to 2.

## Test commands to have ready

```bash
# fast, no network — good for "watch tests pass" without waiting
pytest tests/test_confidence.py tests/test_extractor.py tests/test_report.py -v

# the real thing — everything, ~3-4 min
pytest tests/ -v

# just the bonus agentic loop
pytest tests/test_agentic_hop.py -v

# the actual pipeline run for the deliverable
python -m src.main --domains postman.com supabase.com vapi.ai --report

# try it on domains NOT in the assignment, to prove it generalizes
python -m src.main --domains stripe.com linear.app notion.so --report
```

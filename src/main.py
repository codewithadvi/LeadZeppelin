"""
CLI entrypoint: python -m src.main --domains postman.com supabase.com vapi.ai
"""
import argparse
import asyncio
import json
import logging

from src.pipeline import process_domains
from src.report import write_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Lead Enrichment Agent")
    parser.add_argument(
        "--domains", nargs="+",
        default=["postman.com", "supabase.com", "vapi.ai"],
        help="Company domains to scrape and enrich",
    )
    parser.add_argument("--output", default="output.json", help="Output JSON path")
    parser.add_argument("--report", action="store_true", help="Also generate a human-readable report.html")
    args = parser.parse_args()

    results = asyncio.run(process_domains(args.domains))

    output_data = [r.model_dump() for r in results]
    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)

    if args.report:
        write_report(results, "report.html")
        print("Wrote report.html -- open it in a browser, Ctrl+P to save as PDF")

    print(f"\nWrote {len(results)} records to {args.output}\n")
    for r in results:
        status = "OK" if r.llm_source != "failed" else "FAILED"
        print(f"  [{status}] {r.domain} — confidence={r.confidence_score} source={r.llm_source}"
              f"{f' error={r.error}' if r.error else ''}")


if __name__ == "__main__":
    main()

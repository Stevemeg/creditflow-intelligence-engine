"""
CLI entry point for the rule engine.

Usage:
    python main.py --mode gap_analysis --input sample_data/credit_report.json
    python main.py --mode eligibility --input sample_data/customer_profile.json
    python main.py --mode gap_analysis --input sample_data/credit_report.json --rules rules.yaml --output outputs/result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.evaluator import RuleEngine
from engine.exceptions import RuleEngineError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Softlend Credit Gap Analyser & Loan Eligibility Evaluator"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["gap_analysis", "eligibility"],
        help="Which evaluation mode to run.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON file: a credit report (gap_analysis) or a customer profile (eligibility).",
    )
    parser.add_argument(
        "--rules",
        default="rules.yaml",
        help="Path to the rules.yaml config file (default: rules.yaml).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write the JSON result to (in addition to stdout).",
    )
    args = parser.parse_args()

    try:
        payload = _load_json(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading input file '{args.input}': {exc}", file=sys.stderr)
        return 1

    try:
        engine = RuleEngine(args.rules)
        result = engine.run(args.mode, payload)
    except RuleEngineError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    print(output_json)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_json, encoding="utf-8")

    return 0


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    sys.exit(main())

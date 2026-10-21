from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_prompt_suite(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("prompt suite must be a JSON object")
    return payload


def build_report(prompt_suite: dict[str, Any]) -> dict[str, Any]:
    counts = {
        category: len(prompts) if isinstance(prompts, list) else 0
        for category, prompts in prompt_suite.items()
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories": counts,
        "total_prompts": sum(counts.values()),
        "prompt_suite": prompt_suite,
        "notes": [
            "This baseline report captures scenario coverage for grounded-chat regression checks.",
            "Use it with live simulation outputs to compare action/citation/answerability drift.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate grounded chat baseline report.")
    parser.add_argument(
        "--suite",
        default="backend/tests/fixtures/grounded_prompt_suite.json",
        help="Path to JSON prompt suite fixture.",
    )
    parser.add_argument(
        "--out",
        default="docs/debug/grounded_baseline_report.json",
        help="Output report path.",
    )
    args = parser.parse_args()

    suite_path = Path(args.suite)
    out_path = Path(args.out)
    prompt_suite = _load_prompt_suite(suite_path)
    report = build_report(prompt_suite)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")

    print(f"Wrote baseline report to {out_path}")


if __name__ == "__main__":
    main()

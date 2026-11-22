"""Export a shareable study summary without prompts, source code, or raw traces."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median


def summarize(private_rows):
    fields = ("task", "repetition", "condition", "first", "final", "submissions", "seconds",
              "meter", "status", "error_type", "candidate_sha256")
    rows = [{key: row[key] for key in fields if key in row} for row in private_rows]
    metrics = {}
    for condition in ("ace-flash", "ace-pro", "dsh-flash"):
        group = [r for r in rows if r["condition"] == condition]
        if not group:
            raise ValueError(f"missing condition {condition}")
        observed = [r["meter"] for r in group if r.get("meter")]
        first_pass = sum(r.get("first") == "pass" for r in group)
        final_pass = sum(r.get("final") == "pass" for r in group)
        cost = sum(r["peak_price_estimate_usd"] for r in observed)
        times = [r["seconds"] for r in group if "seconds" in r]
        metrics[condition] = {
            "allocated": len(group),
            "first_pass": first_pass, "final_pass": final_pass,
            "first_compiled_and_ran": sum(r.get("first") in ("functional", "pass") for r in group),
            "final_outcomes": dict(Counter(r.get("final", r.get("status", "unknown")) for r in group)),
            "runs_with_usage": len(observed),
            "median_seconds": round(median(times), 3) if times else None,
            "observed_requests": sum(r["observed_calls"] for r in observed),
            "uncached_input": sum(r["uncached_input"] for r in observed),
            "cached_input": sum(r["cached_input"] for r in observed),
            "output": sum(r["output"] for r in observed),
            "peak_price_estimate_usd": round(cost, 8),
            "peak_cost_per_success_usd": round(cost / final_pass, 8) if final_pass and len(observed) == len(group) else None,
        }
    pairs = {}
    for outcome in ("first", "final"):
        for left, right in (("ace-flash", "ace-pro"), ("ace-flash", "dsh-flash")):
            by_key = {}
            for r in rows:
                key = r["task"], r.get("repetition", 1)
                if r["condition"] in (left, right):
                    group = by_key.setdefault(key, {})
                    if r["condition"] in group:
                        raise ValueError("duplicate trial")
                    group[r["condition"]] = r.get(outcome) == "pass"
            counts = {"left_only": 0, "right_only": 0, "both_pass": 0, "neither": 0}
            for group in by_key.values():
                a, b = group[left], group[right]
                category = ("both_pass" if b else "left_only") if a else ("right_only" if b else "neither")
                counts[category] += 1
            pairs[f"{left} vs {right} ({outcome})"] = counts
    return {"aggregate": metrics, "paired_counts": pairs, "trials": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.results.read_text())), ensure_ascii=False, indent=2))

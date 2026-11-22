"""Export a shareable study summary without prompts, source code, or raw traces."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median


def apply_recovery(rows, corrected):
    """Complete a trial that stopped before requesting a model."""
    def key(row):
        return row["task"], row.get("repetition", 1), row["condition"]

    expected = {
        ("cvdp_copilot_" + name, repetition, "dsh-flash")
        for name in ("coffee_machine_0001", "line_buffer_0003")
        for repetition in (1, 2)
    }
    recovered = {key(row): row for row in corrected}
    if recovered.keys() != expected or len(corrected) != len(expected):
        raise ValueError("recovery must supply the four pre-request input-limit cases")
    audit = []
    merged = []
    for row in rows:
        ident = key(row)
        if ident not in recovered:
            merged.append(row)
            continue
        if row.get("status") != "runner_error" or row.get("error_type") != "ValueError":
            raise ValueError("recovery cannot replace a completed trial")
        replacement = recovered.pop(ident)
        if replacement.get("meter") is None:
            raise ValueError("recovery is missing measured model usage")
        audit.append({
            "task": ident[0], "repetition": ident[1], "condition": ident[2],
            "original": "input limit stopped run before model request",
            "recovered_final": replacement.get("final"),
        })
        merged.append(replacement)
    if recovered:
        raise ValueError("unmatched recovery entries")
    return merged, audit


def summarize(private_rows):
    fields = ("task", "repetition", "condition", "first", "final", "submissions", "seconds",
              "meter", "status", "error_type", "candidate_sha256")
    rows = [{key: row[key] for key in fields if key in row} for row in private_rows]

    def pass_by_two(row):
        meter = row.get("meter")
        return row.get("first") == "pass" or bool(
            meter and meter["observed_calls"] <= 2 and row.get("final") == "pass"
        )

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
            "pass_by_two_observed_calls": sum(pass_by_two(r) for r in group),
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
    for outcome in ("first", "by_two_calls", "final"):
        for left, right in (("ace-flash", "ace-pro"), ("ace-flash", "dsh-flash")):
            by_key = {}
            for r in rows:
                key = r["task"], r.get("repetition", 1)
                if r["condition"] in (left, right):
                    group = by_key.setdefault(key, {})
                    if r["condition"] in group:
                        raise ValueError("duplicate trial")
                    group[r["condition"]] = pass_by_two(r) if outcome == "by_two_calls" else r.get(outcome) == "pass"
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
    parser.add_argument("--recover-expanded-inputs", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.results.read_text())
    audit = None
    if args.recover_expanded_inputs:
        rows, audit = apply_recovery(rows, json.loads(args.recover_expanded_inputs.read_text()))
    result = summarize(rows)
    if audit is not None:
        result["pre_request_recovery"] = audit
    print(json.dumps(result, ensure_ascii=False, indent=2))

"""Export a shareable study summary without prompts, source code, or raw traces."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median

CONDITIONS = ("ace-flash", "ace-pro", "dsh-flash", "dsh-pro")
COMPARISONS = (
    ("ace-flash", "ace-pro"),
    ("ace-flash", "dsh-flash"),
    ("dsh-flash", "dsh-pro"),
    ("ace-pro", "dsh-pro"),
)


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


def summarize(private_rows, conditions=None, comparisons=COMPARISONS):
    fields = ("task", "repetition", "condition", "first", "final", "submissions", "seconds",
              "meter", "status", "error_type", "candidate_sha256", "offline_replay")
    rows = [{key: row[key] for key in fields if key in row} for row in private_rows]

    def pass_by_two(row):
        meter = row.get("meter")
        if meter and "first_passing_request" in meter:
            request = meter["first_passing_request"]
            return request is not None and request <= 2
        return row.get("first") == "pass" or bool(
            meter and meter["observed_calls"] <= 2 and row.get("final") == "pass"
        )

    if conditions is None:
        conditions = CONDITIONS if any(r["condition"] == "dsh-pro" for r in rows) else CONDITIONS[:3]
    metrics = {}
    for condition in conditions:
        group = [r for r in rows if r["condition"] == condition]
        if not group:
            raise ValueError(f"missing condition {condition}")
        observed = [r["meter"] for r in group if r.get("meter")]
        first_pass = sum(r.get("first") == "pass" for r in group)
        final_pass = sum(r.get("final") == "pass" for r in group)
        prices = [r["peak_price_estimate_usd"] for r in observed]
        cost = sum(prices) if all(price is not None for price in prices) else None
        times = [r["seconds"] for r in group if r.get("seconds") is not None]
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
            "peak_price_estimate_usd": round(cost, 8) if cost is not None else None,
            "peak_cost_per_success_usd": round(cost / final_pass, 8)
            if cost is not None and final_pass and len(observed) == len(group) else None,
        }
        if observed and "responses_with_usage" in observed[0]:
            metrics[condition].update(
                responses_with_usage=sum(r["responses_with_usage"] for r in observed),
                truncated_requests=sum(r["truncated_requests"] for r in observed),
            )
    pairs = {}
    for outcome in ("first", "by_two_calls", "final"):
        for left, right in comparisons:
            if left not in metrics or right not in metrics:
                continue
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


def summarize_completion(baseline, extra):
    """Compare the fourth configuration against the three frozen conditions."""
    base_rows = baseline["trials"]
    expected = {(r["task"], r["repetition"]) for r in base_rows if r["condition"] == "dsh-flash"}
    seen = {(r["task"], r["repetition"]) for r in extra}
    if seen != expected or len(seen) != len(extra) or any(r["condition"] != "dsh-pro" for r in extra):
        raise ValueError("the follow-up must match every baseline task and repetition exactly once")
    result = summarize(base_rows + extra)
    if "pre_request_recovery" in baseline:
        result["pre_request_recovery"] = baseline["pre_request_recovery"]
    result["batching"] = {"original": list(CONDITIONS[:3]), "follow_up": ["dsh-pro"]}
    interaction = {}
    for metric in ("first_pass", "pass_by_two_observed_calls", "final_pass"):
        agg = result["aggregate"]
        ace_gain = agg["ace-pro"][metric] - agg["ace-flash"][metric]
        dsh_gain = agg["dsh-pro"][metric] - agg["dsh-flash"][metric]
        interaction[metric] = {
            "ace_pro_minus_flash": ace_gain,
            "dsh_pro_minus_flash": dsh_gain,
            "difference_of_gains": dsh_gain - ace_gain,
            "allocated_per_condition": len(expected),
        }
    result["descriptive_interaction"] = interaction
    return result


def summarize_cross_provider(baseline, added):
    """Pair each new ACE run with both frozen ACE baselines."""
    baseline_ids = ("ace-flash", "ace-pro")
    added_ids = ("ace-claude", "ace-gpt")
    base_rows = [r for r in baseline["trials"] if r["condition"] in baseline_ids]
    expected = {(r["task"], r["repetition"]) for r in base_rows if r["condition"] == baseline_ids[0]}
    for condition in added_ids:
        trials = [r for r in added if r["condition"] == condition]
        if {(r["task"], r["repetition"]) for r in trials} != expected or len(trials) != len(expected):
            raise ValueError(f"cross-provider follow-up does not match baseline trial IDs for {condition}")
    if len(added) != len(added_ids) * len(expected):
        raise ValueError("unexpected follow-up trials")
    conditions = baseline_ids + added_ids
    comparisons = tuple((left, right) for index, left in enumerate(conditions) for right in conditions[index + 1:])
    result = summarize(base_rows + added, conditions, comparisons)
    result["batching"] = {"frozen_baselines": list(baseline_ids), "follow_up": list(added_ids)}
    return result


def summarize_harness_matrix(deepseek_baseline, ace_baseline, added):
    """Complete the two-harness matrix without reassigning published trials."""
    models = ("flash", "pro", "claude", "gpt")
    ace_ids = tuple(f"ace-{model}" for model in models)
    dsh_ids = tuple(f"dsh-{model}" for model in models)
    def trial_key(row):
        return row["task"], row["repetition"], row["condition"]

    frozen = {trial_key(row): row for row in deepseek_baseline["trials"]}
    for row in ace_baseline["trials"]:
        key = trial_key(row)
        if key in frozen and frozen[key] != row:
            raise ValueError("conflicting baseline values")
        frozen[key] = row
    expected = {(r["task"], r["repetition"]) for r in frozen.values() if r["condition"] == ace_ids[0]}
    conditions = ace_ids + dsh_ids
    for row in added:
        key = trial_key(row)
        if row["condition"] not in dsh_ids[2:] or key in frozen:
            raise ValueError("unexpected or duplicate follow-up trial")
        frozen[key] = row
    if frozen.keys() != {(task, run, condition) for task, run in expected for condition in conditions}:
        raise ValueError("the matrix must contain one run for every allocated trial")
    comparisons = tuple(
        (left, right) for group in (ace_ids, dsh_ids)
        for index, left in enumerate(group) for right in group[index + 1:]
    ) + tuple(zip(ace_ids, dsh_ids))
    result = summarize(list(frozen.values()), conditions, comparisons)
    result["batching"] = {
        "deepseek_factorial": list(CONDITIONS),
        "ace_external_models": list(ace_ids[2:]),
        "dsh_external_models": list(dsh_ids[2:]),
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--recover-expanded-inputs", type=Path)
    modes.add_argument("--complete-factorial-with", type=Path)
    modes.add_argument("--cross-provider-with", type=Path)
    modes.add_argument("--harness-matrix-with", type=Path, nargs=2, metavar=("ACE_BASELINE", "DSH_ADDED"))
    args = parser.parse_args()
    rows = json.loads(args.results.read_text())
    if args.complete_factorial_with:
        result = summarize_completion(rows, json.loads(args.complete_factorial_with.read_text()))
    elif args.cross_provider_with:
        result = summarize_cross_provider(rows, json.loads(args.cross_provider_with.read_text()))
    elif args.harness_matrix_with:
        ace, dsh = (json.loads(path.read_text()) for path in args.harness_matrix_with)
        result = summarize_harness_matrix(rows, ace, dsh)
    else:
        audit = None
        if args.recover_expanded_inputs:
            rows, audit = apply_recovery(rows, json.loads(args.recover_expanded_inputs.read_text()))
        result = summarize(rows)
        if audit is not None:
            result["pre_request_recovery"] = audit
    print(json.dumps(result, ensure_ascii=False, indent=2))

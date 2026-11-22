"""Run the predeclared five-task paired study under a confirmed spending limit."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from model_budget import record
from run_ace_study import run_ace
from run_dsh_study import run_dsh
from study_common import LOCAL, ROOT, task_row

PLAN = json.loads((ROOT / "experiments/suite/design.json").read_text())
RATES = PLAN["pricing"]["peak_usd_per_million"]


def reservation(condition):
    prices = RATES[condition["model"]]
    return condition["max_calls"] * (
        PLAN["pricing"]["reservation_input_tokens_per_call"] * prices["miss"]
        + PLAN["pricing"]["max_output_tokens_per_call"] * prices["output"]
    ) / 1e6


def meter(condition, run, result):
    rates = RATES[condition["model"]]
    if condition["agent"] == "ace":
        billed = []
        for path in sorted((run / "api").glob("*/request.json")):
            summary = path.with_name("summary.json")
            if not summary.exists():
                return None
            u = json.loads(summary.read_text())["usage"]
            if u is None:
                return None
            billed.append((u["prompt_cache_miss_tokens"], u["prompt_cache_hit_tokens"], u["completion_tokens"]))
    else:
        if not result.get("usage") or any(u is None for u in result["usage"]):
            return None
        billed = [(u["inputTokens"] + u.get("cacheWriteTokens", 0),
                   u.get("cacheReadTokens", 0), u["outputTokens"]) for u in result["usage"]]
    return {
        "observed_calls": len(billed),
        "uncached_input": sum(x for x, _, _ in billed), "cached_input": sum(y for _, y, _ in billed),
        "output": sum(z for _, _, z in billed),
        "peak_price_estimate_usd": round(sum(x*rates["miss"] + y*rates["hit"] + z*rates["output"]
                                            for x, y, z in billed) / 1e6, 8),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmed-budget-usd", required=True, type=float)
    args = parser.parse_args()
    conditions = PLAN["conditions"]
    tasks = PLAN["task_ids"]
    total = len(tasks) * sum(reservation(c) for c in conditions)
    if not total <= args.confirmed_budget_usd:
        raise SystemExit(f"Full-plan reservation: ${total:.2f}; budget is insufficient.")
    for task in tasks:
        task_row(task)

    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="suite-", dir=LOCAL))
    print(f"Study directory: {directory}", flush=True)
    results = []
    for index, task in enumerate(tasks):
        # Rotate the order to reduce systematic cache and time-order effects.
        for c in conditions[index % 3:] + conditions[:index % 3]:
            print(f"{task} {c['id']}", flush=True)
            try:
                run = (run_ace(task, c["model"], c["rounds"], c["max_calls"], True)
                       if c["agent"] == "ace" else run_dsh(task, c["rounds"]))
                result = json.loads((run / "result.json").read_text())
                scores = result["scores"]
                metered = meter(c, run, result)
                result = {
                    "first": scores[0]["verdict"] if scores else "no_candidate",
                    "final": scores[-1]["verdict"] if scores else "no_candidate",
                    "submissions": len(scores), "seconds": result["seconds"],
                    "meter": metered,
                }
            except Exception as error:
                result = {"status": "runner_error", "error_type": type(error).__name__}
            result.update(task=task, condition=c["id"])
            results.append(result)
            record(directory / f"{len(results):02d}.json", result)
    record(directory / "results.json", results)


if __name__ == "__main__":
    main()

"""Run a predeclared paired study under a confirmed spending limit."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
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


def run_condition(job):
    index, task, repetition, condition = job
    print(f"{task} {condition['id']} repeat {repetition}", flush=True)
    try:
        c = condition
        run = (run_ace(task, c["model"], c["rounds"], c["max_calls"], True)
               if c["agent"] == "ace" else run_dsh(task, c["rounds"], c["model"]))
        result = json.loads((run / "result.json").read_text())
        scores = result["scores"]
        metered = meter(c, run, result)
        result = {
            "first": scores[0]["verdict"] if scores else "no_candidate",
            "final": scores[-1]["verdict"] if scores else "no_candidate",
            "submissions": len(scores), "seconds": result["seconds"],
            "candidate_sha256": [s["candidate_sha256"] for s in scores],
            "meter": metered, "run": str(run.relative_to(LOCAL)),
        }
    except Exception as error:
        result = {"status": "runner_error", "error_type": type(error).__name__}
    result.update(task=task, condition=condition["id"], repetition=repetition)
    return index, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmed-budget-usd", required=True, type=float)
    parser.add_argument("--design", type=Path, help="Optional task list and repetition count")
    parser.add_argument("--condition", help="Run only this condition on the selected design")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=1)
    args = parser.parse_args()
    design = json.loads(args.design.read_text()) if args.design else PLAN
    conditions = [c for c in design.get("conditions", PLAN["conditions"]) if args.condition in (None, c["id"])]
    if not conditions:
        parser.error(f"condition {args.condition!r} is absent from the selected design")
    tasks = design["task_ids"]
    repetitions = design.get("repetitions", 1)
    if len(set(tasks)) != len(tasks) or repetitions not in (1, 2, 3):
        raise SystemExit("Expected unique tasks and one to three repetitions.")
    total = len(tasks) * repetitions * sum(reservation(c) for c in conditions)
    if not total <= args.confirmed_budget_usd:
        raise SystemExit(f"Full-plan reservation: ${total:.2f}; budget is insufficient.")
    for task in tasks:
        task_row(task)

    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="suite-", dir=LOCAL))
    print(f"Study directory: {directory}", flush=True)
    record(directory / "design.json", {"tasks": tasks, "repetitions": repetitions,
                                      "workers": args.workers, "conditions": conditions})
    jobs = []
    for replication in range(1, repetitions + 1):
        for index, task in enumerate(tasks):
            # Rotate condition order across tasks and repetitions.
            offset = (index + replication - 1) % len(conditions)
            for c in conditions[offset:] + conditions[:offset]:
                jobs.append((len(jobs) + 1, task, replication, c))

    results = []
    with ProcessPoolExecutor(args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for index, result in pool.map(run_condition, jobs):
            results.append(result)
            record(directory / f"{index:02d}.json", result)
    record(directory / "results.json", results)


if __name__ == "__main__":
    main()

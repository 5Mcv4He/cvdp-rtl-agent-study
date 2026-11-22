"""Run and export the locked DeepSeek Flash tools-on/off paired study."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
import os
from pathlib import Path
import tempfile

from model_budget import record
from run_dsh_tools_study import MAX_OUTPUT_TOKENS, MAX_REQUEST_BYTES, check_gate, run_tools
from study_common import LOCAL, ROOT, task_row

PLAN = ROOT / "experiments/suite/tools-suite-design.json"
METRICS = ("passed", "budget_exhausted", "completed_submission")


def run_pair_member(task, repetition, condition, rounds, cap):
    enabled = condition["tools_enabled"]
    row = {"task": task, "repetition": repetition, "condition": condition["id"]}
    try:
        directory = run_tools(task, rounds, cap, tools_enabled=enabled)
        result = json.loads((directory / "result.json").read_text())
        measured = result["api_relay"]
        requests = measured["forwarded_requests"]
        if requests > cap or not result["post_run_scan_clean"]:
            raise RuntimeError("matched trial failed the request or isolation check")
        if not enabled and result["tool_calls"]["count"]:
            raise RuntimeError("tools-off execution observed tools")
        submitted = result["completed_scores"]
        last_snapshot = result["scores"][-1]["verdict"] if result["scores"] else None
        outcome = result["outcome"]
        row.update(
            passed=any(s["verdict"] == "pass" for s in submitted),
            budget_exhausted=outcome == "budget_exhausted",
            completed_submission=bool(submitted),
            completed_verdicts=[s["verdict"] for s in submitted],
            last_graded_verdict=last_snapshot, outcome=outcome,
            candidate_origins=result["candidate_origins"],
            candidate_sha256=result["candidate_sha256"],
            requests=requests, sdk_requests_with_usage=result["sdk_events"]["requests_with_usage"],
            provider_responses=measured["requests"], seconds=result["seconds"],
            tool_calls=result["tool_calls"], scan_clean=True,
            run=result["run"],
        )
    except Exception as error:
        row.update(passed=False, budget_exhausted=False, completed_submission=False,
                   outcome="runner_error", error_type=type(error).__name__)
    return row


def summarize(rows, tasks, plan):
    ids = [item["id"] for item in plan["conditions"]]
    pairs = [(task, rep) for rep in range(1, plan["repetitions"] + 1) for task in tasks]
    index = {(r["task"], r["repetition"], r["condition"]): r for r in rows}
    expected = {(task, rep, cond) for task, rep in pairs for cond in ids}
    if len(index) != len(rows) or set(index) != expected:
        raise ValueError("the published study requires a complete paired allocation")
    totals = {}
    for cond in ids:
        group = [index[(task, rep, cond)] for task, rep in pairs]
        totals[cond] = {
            "allocated": len(group), **{key: sum(r[key] for r in group) for key in METRICS},
            "requests": sum(r.get("requests", 0) for r in group),
            "trials_with_request_counts": sum("requests" in r for r in group),
            "outcomes": dict(Counter(r["outcome"] or "finished" for r in group)),
        }
    paired = {}
    for key in METRICS:
        pair_counts = Counter((index[(t, r, ids[0])][key], index[(t, r, ids[1])][key]) for t, r in pairs)
        paired[key] = {"off_only": pair_counts[True, False], "on_only": pair_counts[False, True],
                       "both": pair_counts[True, True], "neither": pair_counts[False, False]}
    return {
        "model": plan["model"], "max_requests": plan["max_requests"], "max_rounds": plan["max_rounds"],
        "max_request_bytes": MAX_REQUEST_BYTES, "max_output_tokens": MAX_OUTPUT_TOKENS,
        "tasks": tasks, "repetitions": plan["repetitions"], "aggregate": totals, "paired_counts": paired,
        "trials": [{k: v for k, v in row.items() if k != "run"} for row in rows],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    os.umask(0o077)
    plan = json.loads(PLAN.read_text())
    tasks = json.loads((PLAN.parent / plan["cohort"]).read_text())["task_ids"]
    for task in tasks:
        task_row(task)
    check_gate()
    directory = Path(tempfile.mkdtemp(prefix="tools-suite-", dir=LOCAL))
    print(f"Study directory: {directory}", flush=True)
    jobs = []
    conditions = plan["conditions"]
    for rep in range(1, plan["repetitions"] + 1):
        for number, task in enumerate(tasks):
            order = conditions if (number + rep) % 2 else conditions[::-1]
            jobs.extend((task, rep, condition, plan["max_rounds"], plan["max_requests"]) for condition in order)
    with ProcessPoolExecutor(args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = {pool.submit(run_pair_member, *job): i for i, job in enumerate(jobs, 1)}
        for future in as_completed(pending):
            row = future.result()
            record(directory / f"{pending[future]:02d}.json", row)
            print(f"{row['task']} {row['condition']} repeat {row['repetition']} completed", flush=True)
    rows = [json.loads(path.read_text()) for path in sorted(directory.glob("[0-9][0-9].json"))]
    record(directory / "summary.json", summarize(rows, tasks, plan))


if __name__ == "__main__":
    main()

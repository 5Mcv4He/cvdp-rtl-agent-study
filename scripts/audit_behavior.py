"""D0: convert the eight audited cases and check their historical evidence links."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile

from replay_postprocess import (
    ACE_SCRIPTS, AUDIT, ace_iteration, ace_visible_choice, matrix_run, read_json,
    sdk_visible_text, sha256,
)
from run_dsh_study import rtl_from_response
from study_common import ACE, FEEDBACK, LOCAL, PILOT_ID, ROOT, task_row


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ref(path, selector=None):
    path = path.resolve(strict=True)
    value = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path.read_bytes())}
    if selector:
        value["selector"] = selector
    return value


class Trace:
    def __init__(self, trial, run, task, condition, target):
        self.run = run
        self.target = target
        self.id = f"v1/{trial}/{task}/{condition}"
        self.manifest = {"schema_version": "behavior-v2-d0/1", "run_id": self.id, "task": task,
                         "condition": condition, "target": target}
        self.events = []
        self.names = set()

    def add(self, name, kind, sources=(), parents=(), **fields):
        event_id = f"{self.id}/{name}"
        require(event_id not in self.names, f"duplicate event: {event_id}")
        require(set(parents) <= self.names, f"unresolved parent: {event_id}")
        event = {"event_id": event_id, "type": kind, "parents": list(parents),
                 "sources": list(sources), **fields}
        self.events.append(event)
        self.names.add(event_id)
        return event_id

    def missing(self, name, field, why, parents=()):
        return self.add(name, "missing", parents=parents, field=field, reason=why)

    def candidate(self, number, content, sources, parents, origin):
        candidate_id = f"{self.id}/candidate-{number}"
        digest = sha256(content)
        event = self.add(f"candidate-{number}", "candidate", sources, parents,
                         candidate_id=candidate_id, sha256=digest, origin=origin)
        return event, digest

    def grade(self, number, replay, candidate, digest, expected):
        source = replay / "verdict.json"
        verdict = read_json(source)
        tested, = (replay / "cvdp").glob("*/harness/*/" + self.target)
        require(sha256(tested.read_bytes()) == verdict["candidate_sha256"] == digest,
                f"{self.id}: archive scored different bytes")
        require(verdict["task_id"] == self.manifest["task"] and verdict["verdict"] == expected,
                f"{self.id}: score does not match historical trial")
        raw = replay / "cvdp/raw_result.json"
        evaluation = read_json(raw)[verdict["task_id"]]
        service, = evaluation["tests"]
        require(expected != "pass" or (evaluation["errors"] == 0 and service["result"] == 0
                                      and verdict["cocotb_tests"] > 0),
                f"{self.id}: passing summary conflicts with underlying evaluator")
        log = Path(service["log"])
        return self.add(f"grade-{number}", "grade",
                        [ref(source), ref(tested), ref(raw), ref(log)], [candidate],
                        candidate_id=candidate, verdict=expected, scope="cvdp_original_tests")

    def save(self, directory):
        # Records are emitted in dependency order. Archive timestamps and SDK
        # sequence numbers are referenced separately from this derived order.
        directory.mkdir()
        (directory / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n")
        with (directory / "events.jsonl").open("x") as stream:
            for ordinal, event in enumerate(self.events, 1):
                stream.write(json.dumps({"ordinal": ordinal, **event}, ensure_ascii=False) + "\n")
        return {
            **self.manifest,
            "events": dict(sorted(Counter(e["type"] for e in self.events).items())),
            "candidate_records": [{k: e[k] for k in ("candidate_id", "sha256", "origin")}
                                  for e in self.events if e["type"] == "candidate"],
            "grades": [e["verdict"] for e in self.events if e["type"] == "grade"],
            "feedback_delivery": [e["scope"] for e in self.events if e["type"] == "feedback_received"],
            "termination": [e["reason"] for e in self.events if e["type"] == "termination"],
            "tool_diagnostics": [e["diagnostic"] for e in self.events if e.get("diagnostic")],
            "missing": [e["field"] for e in self.events if e["type"] == "missing"],
            "checks": ("verified_with_gaps" if any(e["type"] == "missing" for e in self.events)
                       else "verified_in_scope"),
        }


def ace_trace(trace, archived, expected_hashes, extract_code, normalize_sv):
    run = trace.run
    summary, = run.glob("*/datapoints/*/result.json")
    attempt, = read_json(summary)["attempts"]
    ledger = iter(sorted(run.glob("api/*/request.json")))
    previous_evaluator = feedback = None
    finished = []
    for number, expected in enumerate(archived, 1):
        iteration = ace_iteration(run, number)
        generator = iteration / "generator.response.json"
        reply = read_json(generator)
        for path in ledger:
            call = path.parent.name
            request = read_json(path)
            parents = [previous_evaluator] if previous_evaluator else []
            if feedback and any(feedback[0] in msg["content"]
                                for msg in request["body"].get("messages", request["body"].get("input", []))
                                if isinstance(msg.get("content"), str)):
                parents.append(feedback[1])
            req = trace.add(f"request-{call}", "request", [ref(path, "/body")], parents,
                            scope="provider_payload", role=request["role"])
            provider = path.with_name("provider-response")
            choice = ace_visible_choice(path, provider)
            response_id = trace.add(f"response-{call}", "response", [ref(provider)], [req],
                                    finish=choice["finish_reason"])
            if len(parents) == 2:
                trace.add(f"delivered-{call}", "feedback_received", [ref(path, "/body")],
                          [feedback[1], req], scope="provider_payload")
            if (request["role"] == "generator" and
                    choice["message"]["content"].strip() == reply["content"].strip() and
                    choice["finish_reason"] == reply["finish_reason"]):
                break
            require(request["role"] != "generator", "unexpected generator response before archived reply")
        else:
            raise ValueError(f"{trace.id}: no provider response matches generator round {number}")
        post = iteration / "postprocess_result.json"
        archived_post = read_json(post)
        candidate = iteration / "candidate" / trace.target
        before = candidate.with_suffix(candidate.suffix + ".raw")
        if not before.exists():
            before = candidate
        extracted = extract_code(reply["content"]).rstrip() + "\n"
        require(extracted.encode() == before.read_bytes(), "ACE extractor did not reproduce stored bytes")
        transformed, actions = normalize_sv(extracted)
        require([f"{trace.target}: {action}" for action in actions] == archived_post["actions"],
                "ACE postprocessing actions do not match the archive")
        require(transformed.encode() == candidate.read_bytes(), "ACE transformed bytes differ")
        extract = trace.add(f"extract-{number}", "extraction",
                            [ref(generator, "/content"), ref(before)], [response_id],
                            output_sha256=sha256(extracted.encode()))
        post_event = trace.add(f"postprocess-{number}", "postprocess", [ref(post), ref(candidate)],
                               [extract], actions=actions,
                               output_sha256=sha256(transformed.encode()))
        ed, digest = trace.candidate(number, candidate.read_bytes(), [ref(candidate)], [post_event],
                                     "completed_submission")
        require(digest == expected_hashes[number - 1], "ACE candidate hash differs from V1")
        evaluator = trace.add(f"ace-eval-{number}", "harness_evaluation",
                              [ref(iteration / "real_evaluator_result.json"),
                               ref(summary, f"/attempts/0/history/{number - 1}")], [ed])
        feedback_file = iteration / "evaluator_error_report.txt"
        published = trace.add(f"feedback-{number}", "feedback_generated",
                              [ref(feedback_file)], [evaluator])
        feedback = feedback_file.read_text().strip(), published
        trace.grade(number, run / f"replay-{number}", ed, digest, expected["verdict"])
        previous_evaluator = evaluator
        finished = [evaluator]
    require(next(ledger, None) is None, "ACE request ledger has unassociated calls")
    trace.add("end", "termination", [ref(summary, "/attempts/0/status")], finished,
              reason=attempt["status"])


def dsh_trace(trace, row, archived):
    run = trace.run
    turn_files = sorted(run.glob("turn-*.json"))
    grades = []
    for number, path in enumerate(turn_files, 1):
        turn = read_json(path)
        events = turn["events"]
        starts = [i for i, e in enumerate(events) if e["type"] == "step/start"]
        replies = [i for i, e in enumerate(events) if e["type"] == "assistant/message"]
        require(len(starts) == len(replies) == 1 and starts[0] < replies[0],
                "unexpected DSH no-tool SDK steps")
        parents = grades[-1:]
        if number > 1:
            expected = FEEDBACK[archived[number - 2]["verdict"]]
            matches = [i for i, e in enumerate(events[:replies[0]]) if e["type"] == "user/message"
                       and any(b.get("text", "").startswith(expected) for b in e["data"]["content"])]
            position, = matches
            parents = [trace.add(f"feedback-{number}", "feedback_received",
                                 [ref(path, f"/events/{position}")], parents, scope="sdk")]
        step = trace.add(f"request-{number}", "request_observed",
                         [ref(path, f"/events/{starts[0]}")], parents, scope="sdk")
        trace.missing(f"wire-{number}", "provider_request_body", "DSH no-tool run retained SDK events", [step])
        response = trace.add(f"response-{number}", "response",
                             [ref(path, f"/events/{replies[0]}"), ref(path, "/final_response")],
                             [step], finish=turn["finish_reason"], scope="sdk")
        code = rtl_from_response(sdk_visible_text(turn))
        extract = trace.add(f"extract-{number}", "extraction", [ref(path, "/final_response")],
                            [response], output_sha256=sha256(code.encode()) if code else None)
        if code is None:
            require(not (run / f"candidate-{number}.sv").exists(), "unparsed DSH output has candidate")
            trace.add("end", "termination", [ref(path, "/finish_reason"), ref(run / "result.json")],
                      [extract], reason="no_extractable_rtl", model_finish=turn["finish_reason"])
            return
        replay = run / f"replay-{number}"
        origin = "completed_submission"
        if not replay.is_dir():
            require(row.get("offline_replay") and number == 2, "missing DSH historical score")
            expected_hash = row["candidate_sha256"][number - 1]
            found = [p.parent for p in LOCAL.glob("suite-*/saved-turn-replay-*/replay-2/verdict.json")
                     if read_json(p)["candidate_sha256"] == expected_hash]
            require(len(found) == 1, "recovered replay could not be uniquely located")
            replay, = found
            origin = "offline_recovery"
        tested, = (replay / "cvdp").glob("*/harness/*/" + trace.target)
        source = tested if origin == "offline_recovery" else run / f"candidate-{number}.sv"
        require(code.encode() == source.read_bytes(), "DSH extracted bytes differ from scoring input")
        candidate, digest = trace.candidate(number, code.encode(), [ref(source)], [extract], origin)
        require(digest == row["candidate_sha256"][number - 1], "DSH candidate hash differs from V1")
        grade = trace.grade(number, replay, candidate, digest, archived[number - 1]["verdict"])
        grades.append(grade)
    require(len(grades) == len(row["candidate_sha256"]), "DSH candidate count differs from V1")
    if row.get("offline_replay"):
        trace.missing("runtime-result", "original_run_termination_detail",
                      "original runner aborted before storing result.json; offline replay retained", grades[-1:])
    trace.add("end", "termination", [ref(path, "/finish_reason")], [response],
              reason=turn["finish_reason"], scope="last_sdk_turn")


def tool_trace(trace, result):
    meta = trace.run / "meta"
    path = meta / "events-turn-1.json"
    events = read_json(path)
    ledger = sorted(meta.glob("api/*/request.json"))
    steps = [e for e in events if e["type"] == "step/start"]
    summaries = [e for e in events if e["type"] in ("assistant/message", "assistant/attempt")]
    require(len(steps) == len(ledger) == len(summaries), "tool step ledger count mismatch")
    require(len(ledger) - 1 == result["api_relay"]["forwarded_requests"], "tool forwarded count mismatch")
    tool_results = {}
    previous = None
    for step, assistant, request in zip(steps, summaries, ledger):
        call = request.parent.name
        require(int(call) == step["data"]["step"] == assistant["data"]["step"],
                "relay order does not match SDK step")
        body = request.with_name("request-body.json")
        blocks = [b for m in read_json(body)["messages"] if isinstance(m["content"], list)
                  for b in m["content"] if b.get("type") == "tool_result"]
        parents = [previous] if previous else []
        for block in blocks:
            key = block["tool_use_id"]
            require(key in tool_results, "request references unmatched tool result")
            parents.append(tool_results[key])
        note = read_json(request).get("note")
        req = trace.add(f"request-{call}", "request_rejected" if note else "request",
                        [ref(request), ref(body), ref(path, f"/{events.index(step)}")],
                        dict.fromkeys(parents), scope="relay_received", rejection=note)
        if note:
            error = request.with_name("error.json")
            require(assistant["type"] == "assistant/attempt" and read_json(error)["rejected"] == note,
                    "SDK/relay rejection mismatch")
            previous = trace.add(f"rejected-{call}", "runtime_error",
                                 [ref(error), ref(path, f"/{events.index(assistant)}")], [req],
                                 reason=note)
            continue
        provider = request.with_name("provider-response")
        frames = [json.loads(line[5:]) for line in provider.read_text().splitlines()
                  if line.startswith("data:")]
        ids = [f["content_block"]["id"] for f in frames if f.get("type") == "content_block_start"
               and f["content_block"]["type"] == "tool_use"]
        calls = [e for e in events if e["type"] == "tool/call" and e["data"]["step"] == int(call)]
        require(ids == [e["data"]["callId"] for e in calls] and assistant["type"] == "assistant/message",
                "provider/SDK tool calls do not match")
        previous = trace.add(f"response-{call}", "response",
                             [ref(provider), ref(path, f"/{events.index(assistant)}")], [req],
                             scope="provider_and_sdk")
        for action in calls:
            key = action["data"]["callId"]
            completed, = (e for e in events if e["type"] == "tool/result"
                          and e["data"]["message"]["toolCallId"] == key)
            require(action["seq"] > assistant["seq"] and completed["seq"] > action["seq"],
                    "tool result sequence mismatch")
            action_id = trace.add(f"tool-{action['seq']}", "tool_call",
                                  [ref(path, f"/{events.index(action)}")], [previous],
                                  tool=action["data"]["name"])
            text = "\n".join(b.get("text", "") for b in completed["data"]["message"]["content"])
            diagnostic = None
            if "[timed out after " in text:
                diagnostic = "tool_timeout"
            elif "timeout: command not found" in text and "[exit code: 127]" in text:
                diagnostic = "timeout_command_missing"
            tool_results[key] = trace.add(f"tool-result-{completed['seq']}", "tool_result",
                                           [ref(path, f"/{events.index(completed)}")], [action_id],
                                           diagnostic=diagnostic)
    trace.missing("action-versions", "per_action_workspace_bytes", "only the round-end snapshot was saved")
    trace.missing("forwarded-bodies", "exact_upstream_serialized_body",
                  "historical relay saved incoming body before forwarding/clamping")
    end, = (e for e in events if e["type"] == "turn/end")
    reason = {"request_budget": "budget_exhausted", "input_limit": "input_limit"}[note]
    require(reason == result["outcome"] and not result["completed_scores"] and
            not result["external_feedback"], "unexpected tool run termination record")
    stopped = trace.add("end", "termination",
                        [ref(path, f"/{events.index(end)}"), ref(trace.run / "result.json", "/outcome")],
                        [previous], reason=reason)
    source = meta / "candidate-1.sv"
    require(result["candidate_origins"] == ["workspace_snapshot"], "tool snapshot origin differs")
    candidate, digest = trace.candidate(1, source.read_bytes(), [ref(source)], [stopped], "workspace_snapshot")
    require([digest] == result["candidate_sha256"], "tool snapshot hash differs")
    trace.grade(1, meta / "replay-1", candidate, digest, result["scores"][0]["verdict"])


def p2_run():
    archived = next(row for row in read_json(ROOT / "experiments/P2/results.json")
                    if row["condition"] == "ace-flash")
    candidates = []
    for result in (ACE / "outputs").glob("study-*/result.json"):
        row = read_json(result)
        if (row["task_id"], row["model"], row["scores"], row["seconds"]) == (
                PILOT_ID, archived["model"], archived["scores"], archived["seconds"]):
            candidates.append(result.parent)
    run, = candidates
    return run, archived["scores"]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    os.umask(0o077)
    sys.path.insert(0, str(ACE_SCRIPTS))
    from ace_cvdp_native.sv import normalize_generated_sv
    from extract_solution import extract_code

    study = ROOT / "experiments/v2/cases.json"
    archived_tools = read_json(AUDIT / "evidence.json")["tools_cases"]
    public_matrix = read_json(ROOT / "experiments/suite/harness-matrix-results.json")["trials"]
    public_tools = read_json(ROOT / "experiments/suite/tools-suite-results.json")["trials"]
    output = Path(tempfile.mkdtemp(prefix="v2-d0-", dir=LOCAL))
    results = []
    for case in read_json(study):
        reports = []
        for entry in case["trials"]:
            task, condition, rep = entry
            target, = task_row(task)["output"]["context"]
            is_p2 = rep == "p2"
            if is_p2:
                run, scores = p2_run()
                hashes = [s["candidate_sha256"] for s in scores]
            elif condition == "tools-on":
                record, = (r for r in archived_tools if (r["task"], r["repetition"]) == (task, rep))
                run = LOCAL / record["run"]
            else:
                run, row = matrix_run(task, condition, rep)
                public, = (r for r in public_matrix if (r["task"], r["condition"], r["repetition"]) ==
                           (task, condition, rep))
                hashes = row["candidate_sha256"]
                require(hashes == public["candidate_sha256"], "local index differs from V1 release")
                scores = [{"verdict": read_json(run / f"replay-{n}/verdict.json")["verdict"]}
                          for n in range(1, len(hashes) + 1)
                          if (run / f"replay-{n}/verdict.json").exists()]
                if public.get("offline_replay"):
                    scores.append({"verdict": public["final"]})
                if scores:
                    require(scores[0]["verdict"] == public["first"] and
                            scores[-1]["verdict"] == public["final"], "local score differs from V1")
            trial = "p2" if is_p2 else f"{'tools' if condition == 'tools-on' else 'matrix'}/{rep}"
            trace = Trace(trial, run, task, condition, target)
            if condition.startswith("ace"):
                ace_trace(trace, scores, hashes, extract_code, normalize_generated_sv)
            elif condition == "tools-on":
                public, = (r for r in public_tools if (r["task"], r["condition"], r["repetition"]) ==
                           (task, condition, rep))
                result = read_json(run / "result.json")
                require(result["outcome"] == public["outcome"] and
                        result["candidate_sha256"] == public["candidate_sha256"] and
                        result["scores"][-1]["verdict"] == public["last_graded_verdict"] and
                        not public["completed_submission"], "tool evidence differs from V1 release")
                tool_trace(trace, result)
            else:
                dsh_trace(trace, row, scores)
            reports.append(trace.save(output / f"{case['case']}-{len(reports) + 1}"))
        results.append({**case, "verified_runs": reports})
    (output / "summary.json").write_text(json.dumps({"model_requests": 0, "cases": results},
                                                    ensure_ascii=False, indent=2) + "\n")
    print(f"Checked {len(results)} cases and {sum(len(c['verified_runs']) for c in results)} runs.")
    print(output)


if __name__ == "__main__":
    main()

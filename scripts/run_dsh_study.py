"""Run a tool-free DSH session with CVDP feedback between submissions."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import tempfile
import time
from unittest.mock import patch

from micu_api import CLAUDE, HOST, KEY_VARIABLES
from model_budget import ACE_MODELS, record
from study_common import FEEDBACK, LOCAL, PILOT_ID, score, task_row


TOOL_FREE_PATCH = [
    {"id": plugin, "disabled": True}
    for plugin in ("persistent-bash", "persistent-pwsh", "tool-fs", "tool-working-directory", "llm-retry")
] + [{"id": "session-log-deepseek", "config": {"enabled": False}}]


def micu_route(model):
    claude = model == CLAUDE
    route = "micu-claude" if claude else "micu-gpt"
    provider = {
        "api": "anthropic-messages" if claude else "openai-responses",
        "baseURL": HOST if claude else HOST + "/v1",
        "apiKeyEnv": KEY_VARIABLES[model],
        "models": [{"id": model, "contextWindow": 1000000, "maxTokens": 4096,
                    "reasoningEfforts": {"low": "low"}}],
    }
    if claude:
        provider["compat"] = {"forceAdaptiveThinking": True, "supportsTemperature": False}
    patch = {"insert": [{
        "id": "llm-pi-ai", "name": "@deepseek-ai/dsh-llm-pi-ai",
        "config": {"providers": {route: provider}},
    }]}
    return route, patch


def rtl_from_response(response):
    text = response.strip()
    if "```" in text:
        blocks = re.findall(r"```(?:systemverilog|verilog|sv)?[ \t]*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if len(blocks) != 1:
            return None
        text = blocks[0].strip()
    if not text or not re.search(r"\bmodule\s+\w+", text):
        return None
    return text + "\n"


def run_dsh(task, rounds, model="deepseek-flash"):
    from deepseek_harness import DeepSeekHarness

    row = task_row(task)
    out = LOCAL / "dsh-runs"
    out.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="study-", dir=out))
    print(run, flush=True)
    work = run / "solve"
    work.mkdir()
    target, = row["output"]["context"]
    context = "\n".join(f"File: {name}\n```systemverilog\n{source}\n```"
                        for name, source in row["input"]["context"].items())
    output_contract = f"Return the complete corrected contents of {target}. Preserve the module interface. Return only SystemVerilog."
    prompt = "\n\n".join((row["input"]["prompt"], context, output_contract))
    if len(prompt.encode()) > 24000:
        raise ValueError("public task exceeds the DSH study input limit")
    settings = run / "tool-free.yml"
    micu = model in KEY_VARIABLES
    provider = "deepseek-official"
    profile_patch = TOOL_FREE_PATCH
    if micu:
        provider, provider_patch = micu_route(model)
        profile_patch = [*profile_patch, provider_patch]
    settings.write_text(json.dumps(profile_patch))
    (run / "input.txt").write_text(prompt)
    scores = []
    usage = []
    turns = []
    key_variable = KEY_VARIABLES.get(model, "DEEPSEEK_API_KEY")
    start = time.monotonic()
    env = {
        "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
        key_variable: os.environ[key_variable],
    }
    with patch.dict(os.environ, env, clear=True):
        with DeepSeekHarness(
            cwd=str(work), dsh_home=str(work / ".dsh"), profile="sdk-minimal",
            provider=provider, model=model, reasoning_effort="low" if micu else "off",
            max_tokens=4096, patches=(str(settings),),
            request_timeout_seconds=95,
        ) as harness:
            session = harness.start_session()
            for i in range(1, rounds + 1):
                response = session.run(prompt)
                record(run / f"turn-{i}.json", asdict(response))
                if micu:
                    turn = micu_turn(response, provider, model, initial=i == 1)
                    turns.append(turn)
                    if turn["finish"] == "error":
                        break
                for event in response.events:
                    if event["type"] == "assistant/message":
                        usage.append(event["data"].get("usage"))
                candidate = rtl_from_response(response.final_response)
                if candidate is None:
                    break
                snapshot = run / f"candidate-{i}.sv"
                snapshot.write_text(candidate)
                verdict = score(row, snapshot, run / f"replay-{i}")
                scores.append(verdict)
                if micu:
                    turn["verdict"] = verdict["verdict"]
                if verdict["verdict"] not in ("functional", "compile", "timeout"):
                    break
                if len(response.final_response.encode()) > 16000:
                    break
                prompt = FEEDBACK[verdict["verdict"]] + " " + output_contract
    result = {
        "task_id": task, "agent": "dsh", "model": model, "compact_feedback": True,
        "seconds": round(time.monotonic() - start, 3), "scores": scores, "usage": usage,
    }
    if micu:
        result["turns"] = turns
    record(run / "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return run


def micu_turn(response, provider, model, *, initial):
    calls = [event for event in response.events if event["type"] in ("assistant/message", "assistant/attempt")]
    headers = [event["data"]["header"]["config"] for event in response.events if event["type"] == "request/header"]
    if len(calls) != 1 or (initial and not headers):
        raise ValueError("the no-tool DSH turn must observe exactly one model request")
    if any(h.get("model") != model or h.get("provider") != provider or h.get("reasoningEffort") != "low"
           for h in headers):
        raise ValueError("unexpected DSH model configuration")
    if any(event["type"].startswith(("tool/", "tool-call/")) for event in response.events):
        raise ValueError("tool execution observed in the no-tool condition")
    data = calls[0]["data"]
    for event in data.get("stream", []):
        state = (event.get("chunk") or {}).get("replayState") or {}
        reply = state.get("response")
        if reply and (reply.get("provider") != provider or reply.get("model") != model):
            raise ValueError("unexpected DSH response route")
    return {"finish": response.finish_reason, "usage": data.get("usage")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=PILOT_ID)
    parser.add_argument("--rounds", choices=(1, 2), type=int, default=2)
    parser.add_argument("--model", choices=sorted(ACE_MODELS), default="deepseek-flash")
    args = parser.parse_args()
    os.umask(0o077)
    run_dsh(args.task, args.rounds, args.model)

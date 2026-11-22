"""Run a tool-enabled DSH session on a locked CVDP task with sandboxed tools.

Compared with the tool-free runner (run_dsh_study.py), this condition keeps the
same model, reasoning mode, two-round structure, category-only CVDP feedback,
and final `local_import` scoring, but lets the model work inside a private
workspace with DSH's persistent bash and filesystem tools.

Isolation layers, each verified by the mock-driven probe (`--probe`) before any
paid request:
- outer seatbelt (this launcher): denies file reads under the work tree and the
  user home except the workspace, the runtime binary, and Icarus Verilog, and
  denies outbound network except the loopback relay;
- DSH sandbox-policy `workspace-write`: filesystem tools are fenced in-process
  and the persistent bash runs under a workspace-write seatbelt;
- environment: the runtime is launched with a cleared environment and a dummy
  key; the real key lives only in this process and the relay;
- loopback relay (dsh_tools_relay): metering, request/output caps, fixed
  upstream, and a provider-level ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import time
from unittest.mock import patch

from dsh_tools_relay import Relay, text_message, tool_call_message
from model_budget import record
from run_dsh_study import TOOL_FREE_PATCH, rtl_from_response
from study_common import FEEDBACK, LOCAL, PILOT_ID, ROOT, score, task_row

MODEL = "deepseek-flash"
DUMMY_KEY = "local-study-relay-dummy"
LAYOUT_VERSION = 4
MAX_REQUEST_BYTES = 48000
MAX_OUTPUT_TOKENS = 4096
WORK_ROOT = os.path.realpath(str(ROOT.parents[1]))
HOME_ROOT = os.path.realpath(str(Path.home()))
RUNTIME_DIR = None  # resolved lazily from the installed SDK runtime
ICARUS_ROOT = LOCAL / "tools/icarus-verilog/13.0"
RUNS = LOCAL / "dsh-tools-runs"
GATE_FILE = LOCAL / "dsh-tools-acceptance.json"
RETRYABLE = ("functional", "compile", "timeout")


def runtime_dir():
    global RUNTIME_DIR
    if RUNTIME_DIR is None:
        from deepseek_harness_runtime import bundled_package_dir
        RUNTIME_DIR = bundled_package_dir() / "runtime"
    return RUNTIME_DIR


def sbpl(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def ancestors(path):
    """The chain of directories above `path` down to the denied roots."""
    resolved = Path(os.path.realpath(path))
    chain = []
    for parent in resolved.parents:
        chain.append(parent)
        if str(parent) in (WORK_ROOT, HOME_ROOT, "/"):
            break
    return chain


def seatbelt_profile_text(solve, relay_port="<PORT>"):
    """One outer seatbelt owning read, write, and network confinement.

    DSH's own sandbox cannot nest here: macOS rejects sandbox_apply from an
    already-sandboxed process, so DSH stays in danger-full-access mode and this
    profile provides the actual fences for every runtime child.
    """
    # Path resolution (realpath, stat) needs file-read-metadata on every
    # ancestor inside the denied trees; contents and directory listings of the
    # ancestors stay denied because file-read-data is not re-allowed.
    traversal = sorted({str(p) for target in (solve, runtime_dir(), ICARUS_ROOT)
                        for p in ancestors(target)})
    forms = [
        "(version 1)",
        "(allow default)",
        f"(deny file-read* (subpath {sbpl(WORK_ROOT)}))",
        f"(deny file-read* (subpath {sbpl(HOME_ROOT)}))",
        "(allow file-read-metadata "
        + " ".join(f"(literal {sbpl(p)})" for p in traversal) + ")",
        f"(allow file-read* (subpath {sbpl(os.path.realpath(solve))}))",
        f"(allow file-read* (subpath {sbpl(os.path.realpath(runtime_dir()))}))",
        f"(allow file-read* (subpath {sbpl(os.path.realpath(ICARUS_ROOT))}))",
        "(deny file-write*)",
        '(allow file-write* (literal "/dev/null") (literal "/dev/ptmx") '
        '(regex #"^/dev/ttys[0-9]+$") (subpath "/private/tmp") '
        '(subpath "/tmp") (subpath "/private/var/folders") '
        f"(subpath {sbpl(os.path.realpath(solve))}))",
        "(deny network*)",
        f'(allow network-outbound (remote ip "localhost:{relay_port}"))',
    ]
    return "\n".join(forms) + "\n"


def tools_patch_text(solve):
    """Tools-on overlay for the sdk-minimal profile.

    The persistent PTY shell is replaced by the ordinary bash tool: the SEA
    runtime cannot allocate PTYs under any sandbox-exec wrapper, so commands
    run through the subprocess-based executor instead (`bash-sandbox` in
    danger-full-access mode executes plain, without nested confinement). The
    launcher seatbelt provides the actual read/write/network fences; no
    sandbox-policy entry is added, so DSH never spawns nested sandbox-exec.
    """
    return (
        "- id: persistent-bash\n"
        "  disabled: true\n"
        "- id: terminal-bash\n"
        "  disabled: true\n"
        "- id: terminal-pwsh\n"
        "  disabled: true\n"
        "- id: pty\n"
        "  disabled: true\n"
        "- insert:\n"
        "    - id: shell-env\n"
        "      name: '@deepseek-ai/dsh-shell-env'\n"
        "    - id: bash-sandbox\n"
        "      name: '@deepseek-ai/dsh-bash-sandbox'\n"
        "      config:\n        timeoutMs: 300000\n"
        "    - id: tool-bash\n"
        "      name: '@deepseek-ai/dsh-tool-bash'\n"
        "- id: tool-fs\n"
        "  config:\n    read: true\n    readImage: false\n    write: true\n    edit: true\n"
        "- id: llm-retry\n  disabled: true\n"
        "- id: session-log-deepseek\n  config:\n    enabled: false\n"
    )


def fingerprint():
    """Stable identity of the isolation configuration, independent of run paths."""
    digest = hashlib.sha256()
    digest.update(f"layout={LAYOUT_VERSION}\n".encode())
    digest.update(seatbelt_profile_text("<SOLVE>").encode())
    digest.update(tools_patch_text("<SOLVE>").encode())
    digest.update(json.dumps(TOOL_FREE_PATCH).encode())
    digest.update(f"runtime={runtime_dir()}\nicarus={ICARUS_ROOT}\n".encode())
    digest.update((ROOT / "scripts/dsh_tools_relay.py").read_bytes())
    digest.update((ROOT / "scripts/run_dsh_tools_study.py").read_bytes())
    return digest.hexdigest()


def contract_text(target, tools_enabled=True):
    if not tools_enabled:
        return f"Return the complete corrected contents of {target}. Preserve the module interface. Return only SystemVerilog."
    return (f"The file {target} in your workspace is the submission. Edit that file in place with "
            "your tools; final grading reads exactly those bytes. Preserve the module interface. "
            f"For local checks you may run: iverilog -g2012 -o sim.vvp {target} your_testbench.sv "
            "&& vvp sim.vvp. Do not modify task.md. Official CVDP grading with the full test suite "
            "runs outside your workspace; its per-round feedback states only the result category.")


def build_prompt(row, target, tools_enabled=True):
    context = "\n".join(f"File: {name}\n```systemverilog\n{source}\n```"
                        for name, source in row["input"]["context"].items())
    prompt = "\n\n".join((row["input"]["prompt"], context, contract_text(target, tools_enabled)))
    if len(prompt.encode()) > 24000:
        raise ValueError("public task exceeds the DSH tools study input limit")
    return prompt


def build_workspace(solve, row):
    (solve / "rtl").mkdir(parents=True)
    target, = row["output"]["context"]
    (solve / target).write_text(row["input"]["context"][target])
    (solve / "task.md").write_text(row["input"]["prompt"])
    return target


def place_sentinels(meta):
    """Synthetic canary files at the protected locations."""
    token = os.urandom(6).hex()
    locations = [
        Path(HOME_ROOT) / f"dsh-study-sentinel-{token}",
        Path(WORK_ROOT) / f"dsh-study-sentinel-{token}",
        LOCAL / "data" / f"dsh-study-sentinel-{token}",
        LOCAL / "score" / f"dsh-study-sentinel-{token}",
        meta / f"dsh-study-sentinel-{token}",
    ]
    canaries = []
    for location in locations:
        canary = f"DSH-STUDY-CANARY-{os.urandom(12).hex()}"
        location.write_text(canary + "\n")
        canaries.append(canary)
    return locations, canaries


def remove_sentinels(locations):
    for location in locations:
        try:
            location.unlink()
        except FileNotFoundError:
            pass


def probe_bash_command(sentinel_paths, dataset_path, escape_path, target):
    cats = " ".join(shlex.quote(str(p)) for p in sentinel_paths)
    return (
        "command -v iverilog > probe-iverilog-path.txt 2>&1 || true\n"
        "iverilog -V > probe-iverilog.txt 2>&1 || true\n"
        "env | sort > probe-env.txt\n"
        "ps -E -a -x > probe-ps-all-env.txt 2>&1 || true\n"
        "printf 'workspace-write-ok\\n' > probe-write-proof.txt\n"
        f"for p in {cats}; do printf '== %s\\n' \"$p\"; cat \"$p\" 2>&1; done > probe-sentinels.txt\n"
        f"head -c 2000 {shlex.quote(str(dataset_path))} > probe-dataset.txt 2>&1 || true\n"
        "curl -s --max-time 3 https://example.com/ > probe-curl.txt 2>&1; "
        "printf 'curl_rc=%s\\n' \"$?\" >> probe-curl.txt\n"
        "{ printf 'escape' > " + shlex.quote(str(escape_path)) + "; } 2> probe-inner-fence.txt; "
        "printf 'rc=%s\\n' \"$?\" >> probe-inner-fence.txt\n"
        f"cp {shlex.quote(target)} probe-read-copy.txt 2>&1 || true\n"
    )


def probe_final_text():
    return ("Probe complete.\n\n```systemverilog\nmodule probe_mock_acceptance();\n"
            "  initial begin #1 $display(\"mock\"); end\nendmodule\n```")


class ProbeScript:
    """Scripted mock responses driving the isolation probes through real tools."""

    def __init__(self, target, escape_path, probe_command):
        self.target = target
        self.escape_path = str(escape_path)
        self.probe_command = probe_command
        self.final = probe_final_text()

    def respond(self, index, payload):
        if index == 1:
            return tool_call_message("bash", {"description": "Run the isolation probes",
                                              "command": self.probe_command}, 120, 20, step=1)
        if index == 2:
            return tool_call_message("write", {"file_path": "notes/probe-fs-write.txt",
                                               "content": "fs write works\n"}, 200, 15, step=index)
        if index == 3:
            return tool_call_message("write", {"file_path": self.escape_path,
                                               "content": "escape attempt"}, 240, 12, step=index)
        if index == 4:
            return tool_call_message("edit", {"file_path": "notes/probe-fs-write.txt",
                                              "old_string": "works", "new_string": "works EDITED"},
                                     280, 15, step=index)
        if index == 5:
            return tool_call_message("read", {"file_path": self.target}, 320, 12, step=index)
        if index == 6:
            return tool_call_message(
                "bash",
                {"description": "Echo the filesystem-tool evidence and the RTL head",
                 "command": "cat notes/probe-fs-write.txt > probe-fs-write-echo.txt 2>&1 || true; "
                            f"head -c 400 {shlex.quote(self.target)} > probe-rtl-head.txt 2>&1 || true"},
                360, 18, step=index)
        return text_message(self.final, 400, 40, message_id=f"msg_mock_{index:02d}")


def scan_model_reachable(run, patterns):
    """Scan what the model could read or exfiltrate: the workspace and the relay ledger bodies."""
    hits = {pattern: [] for pattern in patterns}
    for path in (run / "solve").rglob("*"):
        if path.is_file():
            try:
                blob = path.read_bytes()
            except OSError:
                continue
            for pattern in patterns:
                if pattern.encode() in blob:
                    hits[pattern].append("solve/" + str(path.relative_to(run / "solve")))
    api = run / "meta/api"
    if api.is_dir():
        for path in sorted(api.glob("*/request-body.json")):
            blob = path.read_bytes()
            for pattern in patterns:
                if pattern.encode() in blob:
                    hits[pattern].append("api/" + path.parent.name + "/request-body.json")
    return hits


def evaluate_acceptance(run, solve, sentinel_paths, canaries, escape_path,
                        work_write_probe, scan_key, dataset_path):
    other_task = "cvdp_copilot_64b66b_encoder_0005"

    def read(name):
        path = solve / name
        return path.read_text(errors="replace") if path.exists() else ""

    sentinels_out = read("probe-sentinels.txt")
    ps_all = read("probe-ps-all-env.txt")
    env_names = [line.split("=")[0] for line in read("probe-env.txt").splitlines() if "=" in line]
    checks = {
        "bash_workspace_write": "workspace-write-ok" in read("probe-write-proof.txt"),
        "fs_write_and_edit": "fs write works EDITED" in read("notes/probe-fs-write.txt"),
        "workspace_read": "module" in read("probe-read-copy.txt"),
        "fs_escape_denied": not escape_path.exists(),
        "work_tree_write_denied": not work_write_probe.exists() and "rc=0" not in read("probe-inner-fence.txt"),
        "sentinel_reads_denied": (
            all(canary not in sentinels_out for canary in canaries)
            and sentinels_out.count("==") == len(sentinel_paths)
            and ("Operation not permitted" in sentinels_out or "Permission denied" in sentinels_out)
        ),
        "dataset_denied": other_task not in read("probe-dataset.txt"),
        "tool_env_no_credentials": not any(
            re.search(r"(KEY|TOKEN|SECRET|PASSWORD)", name, re.IGNORECASE) for name in env_names),
        "process_env_inspection_blocked": "Operation not permitted" in ps_all,
        "network_denied": ("Example Domain" not in read("probe-curl.txt")
                           and "curl_rc=0" not in read("probe-curl.txt")),
        "iverilog_reachable": "Icarus Verilog" in read("probe-iverilog.txt"),
    }
    patterns = list(canaries) + [other_task]
    if scan_key:
        patterns.append(scan_key)
    leaks = scan_model_reachable(run, patterns)
    checks["model_reachable_scan_clean"] = all(not paths for paths in leaks.values())
    observations = {
        "tool_env_relay_url_disclosed": "DEEPSEEK_BASE_URL" in env_names,
        "tool_env_dsh_prefix_disclosed": any(name.startswith("DSH_") for name in env_names),
        "ps_capture_bytes": len(ps_all.encode()),
    }
    return {
        "passed": all(checks.values()), "checks": checks,
        "layout_version": LAYOUT_VERSION,
        "scan_hits": {k: v for k, v in leaks.items() if v},
        "observations": observations,
    }


def open_harness(solve, config_dir, relay, tools_enabled=True):
    """Launch the runtime under the outer seatbelt.

    The seatbelt profile and the tools patch live in ``config_dir`` outside the
    denied trees: the runtime must read them at startup, they carry no secrets,
    and they stay out of the model-facing workspace.
    """
    from deepseek_harness import DeepSeekHarness

    profile_path = config_dir / "seatbelt.sbpl"
    profile_text = seatbelt_profile_text(solve, relay.port)
    profile_path.write_text(profile_text)
    patch_path = config_dir / "tools-profile.yml"
    patch_path.write_text(tools_patch_text(solve) if tools_enabled else json.dumps(TOOL_FREE_PATCH))
    runtime_exe = runtime_dir() / "deepseek-harness-sdk-runtime-macos-arm64"
    env = {
        "PATH": "/usr/bin:/bin:" + str(ICARUS_ROOT / "bin"),
        "LANG": "en_US.UTF-8", "HOME": str(solve),
        # A custom _launch_args bypasses the SDK's default argv builder, so the
        # profile, patches, and DSH_HOME are appended here explicitly.
        "DSH_HOME": str(solve / ".dsh"),
    }
    launch_args = ("sandbox-exec", "-p", profile_text, str(runtime_exe),
                   "--profile", "sdk-minimal", "--patch", str(patch_path))
    harness = DeepSeekHarness(
        cwd=str(solve), profile="sdk-minimal",
        model=MODEL, reasoning_effort="off", max_tokens=MAX_OUTPUT_TOKENS,
        request_timeout_seconds=95,
        base_url=relay.base_url, api_key=DUMMY_KEY, env=env,
        _launch_args=launch_args,
    )
    return harness, env


def digest_turn(events, target):
    usage = []
    tool_calls = []
    for event in events:
        etype = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if etype == "assistant/message":
            usage.append(data.get("usage"))
        elif etype == "tool/call":
            blob = json.dumps(event, ensure_ascii=False)
            tool_calls.append({
                "tool": data.get("toolName") or data.get("name") or data.get("tool"),
                "touches_target": target in blob,
                "local_check": any(marker in blob for marker in ("iverilog", "vvp ")),
            })
    return {"usage": usage, "tool_calls": tool_calls}


def classify_turn_error(meta, served):
    api = meta / "api"
    if api.is_dir() and served > 0:
        last = api / f"{served:02d}"
        if (last / "error.json").exists():
            reason = json.loads((last / "error.json").read_text()).get("rejected")
            return {"request_budget": "budget_exhausted",
                    "input_limit": "input_limit"}.get(reason, "relay_rejected")
    return "model_turn_error"


def run_session_flow(run, solve, meta, relay, row, target, initial_prompt, rounds, tools_enabled=True):
    """Drive prompt rounds, snapshot the workspace candidate, and score after each round."""
    scores = []
    turns = []
    usage = []
    tool_calls = []
    finish_reasons = []
    feedback_given = []
    initial = (solve / target).read_bytes()
    start = time.monotonic()
    outcome = None
    prompt = initial_prompt
    config_dir = Path(tempfile.mkdtemp(prefix="dsh-study-config-"))
    completed_scores = []
    candidate_origins = []
    harness, env = open_harness(solve, config_dir, relay, tools_enabled)
    try:
        with patch.dict(os.environ, env, clear=True):
            with harness as active:
                session = active.start_session()
                for index in range(1, rounds + 1):
                    response = session.run(prompt)
                    record(meta / f"events-turn-{index}.json", list(response.events))
                    digested = digest_turn(response.events, target)
                    turns.append({"round": index, "finish_reason": response.finish_reason,
                                  "sdk_requests": len(digested["usage"]),
                                  "tool_calls": digested["tool_calls"]})
                    usage.extend(digested["usage"])
                    tool_calls.extend(digested["tool_calls"])
                    finish_reasons.append(response.finish_reason)
                    if not tools_enabled and digested["tool_calls"]:
                        raise ValueError("the tools-off configuration observed a tool call")
                    completed = response.finish_reason == "completed"
                    candidate_path = solve / target
                    snapshot = meta / f"candidate-{index}.sv"
                    if tools_enabled:
                        if not candidate_path.exists() or candidate_path.is_symlink():
                            outcome = "no_submission"
                            break
                        snapshot.write_bytes(candidate_path.read_bytes())
                    else:
                        rtl = rtl_from_response(response.final_response) if completed else None
                        if rtl is None or not re.search(r"\bendmodule\b", rtl):
                            outcome = "no_submission"
                            break
                        snapshot.write_text(rtl)
                    candidate_origins.append("completed_submission" if completed else "workspace_snapshot")
                    try:
                        verdict = score(row, snapshot, meta / f"replay-{index}")
                    except ValueError as error:
                        outcome = ("unsupported_content"
                                   if "unsupported candidate content" in str(error)
                                   else "scoring_error")
                        record(meta / f"scoring-error-{index}.json",
                               {"error_type": type(error).__name__})
                        break
                    scores.append(verdict)
                    if completed:
                        completed_scores.append(verdict)
                    else:
                        break
                    if index == rounds or verdict["verdict"] not in RETRYABLE:
                        break
                    if relay.admitted >= relay.max_requests:
                        outcome = "budget_exhausted"
                        break
                    feedback = FEEDBACK[verdict["verdict"]]
                    feedback_given.append(verdict["verdict"])
                    prompt = feedback + " " + contract_text(target, tools_enabled)
    finally:
        for name in ("seatbelt.sbpl", "tools-profile.yml"):
            source = config_dir / name
            if source.exists():
                (meta / name).write_bytes(source.read_bytes())
        shutil.rmtree(config_dir, ignore_errors=True)
    if "request_budget" in relay.rejections:
        outcome = "budget_exhausted"
    elif "input_limit" in relay.rejections:
        outcome = "input_limit"
    elif outcome is None and any(reason == "error" for reason in finish_reasons):
        outcome = classify_turn_error(meta, relay.served)
    return {
        "scores": scores, "completed_scores": completed_scores, "candidate_origins": candidate_origins,
        "turns": turns, "usage": usage, "tool_calls": tool_calls,
        "finish_reasons": finish_reasons, "feedback_given": feedback_given,
        "outcome": outcome, "seconds": round(time.monotonic() - start, 3),
        "initial_sha256": hashlib.sha256(initial).hexdigest(),
    }


def probe():
    """Offline acceptance: drive the isolation probes through the real tool stack."""
    accepted_fingerprint = fingerprint()
    row = task_row(PILOT_ID)
    RUNS.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="probe-", dir=RUNS))
    solve = run / "solve"
    meta = run / "meta"
    solve.mkdir()
    meta.mkdir()
    target = build_workspace(solve, row)
    escape_path = Path(WORK_ROOT) / f"dsh-probe-escape-{os.urandom(4).hex()}"
    work_write_probe = Path(WORK_ROOT) / f"dsh-probe-write-{os.urandom(4).hex()}"
    sentinel_paths, canaries = place_sentinels(meta)
    dataset_path = LOCAL / "data" / json.loads(
        (ROOT / "experiments/P0/lock.json").read_text())["dataset"]["file"]
    command = probe_bash_command(sentinel_paths, dataset_path, work_write_probe, target)
    script = ProbeScript(target, escape_path, command)
    relay = Relay(ledger_dir=meta / "api", mock_script=script).bind()
    # Scan for a key-shaped canary even without a real credential present, so
    # the run-directory scan exercises the same code path as a real run.
    scan_key = os.environ.get("DEEPSEEK_API_KEY") or f"DSH-STUDY-FAKEKEY-{os.urandom(8).hex()}"
    try:
        flow = run_session_flow(run, solve, meta, relay, row, target,
                                "Run the environment probes and finish.", rounds=1)
        acceptance = evaluate_acceptance(run, solve, sentinel_paths, canaries,
                                         escape_path, work_write_probe, scan_key, dataset_path)
        acceptance["fingerprint"] = accepted_fingerprint
        acceptance["relay_served"] = relay.served
        acceptance["sdk_requests"] = len(flow["usage"])
        acceptance["relay_matches_sdk"] = relay.served == len(flow["usage"])
        acceptance["pipeline_scores"] = flow["scores"]
        acceptance["probe_run"] = str(run.relative_to(LOCAL))
        acceptance["fingerprint_stable"] = fingerprint() == accepted_fingerprint
        acceptance["passed"] = acceptance["passed"] and acceptance["fingerprint_stable"]
        record(meta / "acceptance.json", acceptance)
        gate = {k: acceptance[k] for k in ("checks", "fingerprint", "layout_version", "probe_run")}
        gate["passed"] = acceptance["passed"] and acceptance["relay_matches_sdk"]
        gate["as_of"] = time.strftime("%Y-%m-%d %H:%M:%S")
        # Keep each acceptance report and atomically refresh the gate for real runs.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=GATE_FILE.parent,
                                         prefix=".dsh-tools-gate-", delete=False) as file:
            pending = Path(file.name)
            try:
                json.dump(gate, file, ensure_ascii=False, indent=2)
                file.flush()
                pending.replace(GATE_FILE)
            finally:
                pending.unlink(missing_ok=True)
        return run, acceptance
    finally:
        relay.shutdown()
        remove_sentinels(sentinel_paths)
        for leftover in (escape_path, work_write_probe):
            try:
                leftover.unlink()
            except FileNotFoundError:
                pass


def check_gate():
    if not GATE_FILE.exists():
        raise SystemExit(
            "No passing isolation acceptance found. Run the offline probe first:\n"
            "  .local/dsh-venv/bin/python scripts/run_dsh_tools_study.py --probe")
    gate = json.loads(GATE_FILE.read_text())
    if not gate.get("passed"):
        raise SystemExit("The recorded isolation acceptance did not pass; rerun --probe.")
    if gate.get("fingerprint") != fingerprint():
        raise SystemExit(
            "The isolation configuration changed since the last acceptance. Rerun --probe:\n"
            "  .local/dsh-venv/bin/python scripts/run_dsh_tools_study.py --probe")
    return gate


def run_tools(task, rounds, max_requests, tools_enabled=True):
    gate = check_gate()
    if "DEEPSEEK_API_KEY" not in os.environ:
        raise SystemExit(
            "Provide the credential inline (not exported in the parent shell), so no ancestor "
            "process environment carries it:\n"
            "  DEEPSEEK_API_KEY=... .local/dsh-venv/bin/python scripts/run_dsh_tools_study.py "
            "--task ...")
    real_key = os.environ["DEEPSEEK_API_KEY"]
    row = task_row(task)
    RUNS.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="tools-", dir=RUNS))
    solve = run / "solve"
    meta = run / "meta"
    solve.mkdir()
    meta.mkdir()
    target = build_workspace(solve, row)
    sentinel_paths, canaries = place_sentinels(meta)
    relay = Relay(ledger_dir=meta / "api", api_key=real_key,
                  max_requests=max_requests, max_request_bytes=MAX_REQUEST_BYTES,
                  max_output_tokens=MAX_OUTPUT_TOKENS).bind()
    print(run, flush=True)
    try:
        flow = run_session_flow(run, solve, meta, relay, row, target,
                                build_prompt(row, target, tools_enabled), rounds, tools_enabled)
    finally:
        relay.shutdown()
        remove_sentinels(sentinel_paths)
    patterns = list(canaries) + [real_key, "cvdp_copilot_64b66b_encoder_0005"]
    patterns = [pattern for pattern in patterns if pattern != task]
    leaks = scan_model_reachable(run, patterns)
    scan_clean = all(not paths for paths in leaks.values())
    record(meta / "post-run-scan.json", {
        "clean": scan_clean, "hits": {k: v for k, v in leaks.items() if v},
        "relay_rejections": relay.rejections,
    })
    scores = flow["scores"]
    candidate_hashes = []
    for index in range(1, len(scores) + 1):
        path = meta / f"candidate-{index}.sv"
        candidate_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    relay_usage = []
    api = meta / "api"
    if api.is_dir():
        for path in sorted(api.glob("*/summary.json")):
            relay_usage.append(json.loads(path.read_text()))
    result = {
        "task_id": task, "agent": "dsh-tools", "model": MODEL, "tools_enabled": tools_enabled,
        "compact_feedback": True, "seconds": flow["seconds"],
        "scores": scores,
        "completed_scores": flow["completed_scores"],
        "candidate_origins": flow["candidate_origins"],
        "candidate_sha256": candidate_hashes,
        "candidate_changed": [h != flow["initial_sha256"] for h in candidate_hashes],
        "sdk_events": {"requests_with_usage": len(flow["usage"]), "usage": flow["usage"],
                       "source": "DeepSeek Harness SDK assistant/message events"},
        "api_relay": {"requests": len(relay_usage), "mode": "forward",
                      "forwarded_requests": relay.forwarded,
                      "upstream_fixed": "api.deepseek.com/anthropic",
                      "caps": {"max_requests": max_requests,
                               "max_request_bytes": MAX_REQUEST_BYTES,
                               "max_output_tokens": MAX_OUTPUT_TOKENS},
                      "summaries": relay_usage,
                      "source": "loopback relay provider-level ledger"},
        "relay_matches_sdk": len(relay_usage) == len(flow["usage"]),
        "tool_calls": {"count": len(flow["tool_calls"]),
                       "local_check_calls": sum(1 for c in flow["tool_calls"] if c["local_check"]),
                       "target_touches": sum(1 for c in flow["tool_calls"] if c["touches_target"])},
        "turn_finish_reasons": flow["finish_reasons"],
        "external_feedback": flow["feedback_given"],
        "outcome": flow["outcome"], "post_run_scan_clean": scan_clean,
        "isolation_gate": {"fingerprint": gate["fingerprint"], "probe_run": gate["probe_run"]},
        "run": str(run.relative_to(LOCAL)),
    }
    if scores:
        result["first"] = scores[0]["verdict"]
        result["final"] = scores[-1]["verdict"]
        result["submissions"] = len(scores)
    record(run / "result.json", result)
    summary = {"task_id": task, "run": result["run"],
               "relay_matches_sdk": result["relay_matches_sdk"],
               "post_run_scan_clean": scan_clean}
    if scores:
        summary.update(first=result["first"], final=result["final"],
                       submissions=result["submissions"])
    summary["outcome"] = result["outcome"]
    print(json.dumps(summary, ensure_ascii=False))
    return run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=PILOT_ID)
    parser.add_argument("--rounds", choices=(1, 2), type=int, default=2)
    parser.add_argument("--max-requests", type=int, default=8)
    parser.add_argument("--tools-off", action="store_true", help="disable tools while retaining the relay and sandbox")
    parser.add_argument("--probe", action="store_true",
                        help="run the offline mock-driven isolation acceptance; no paid requests")
    args = parser.parse_args()
    os.umask(0o077)
    if args.probe:
        run, acceptance = probe()
        print(json.dumps(acceptance, ensure_ascii=False, indent=2))
        raise SystemExit(0 if acceptance["passed"] and acceptance["relay_matches_sdk"] else 1)
    run_tools(args.task, args.rounds, args.max_requests, tools_enabled=not args.tools_off)

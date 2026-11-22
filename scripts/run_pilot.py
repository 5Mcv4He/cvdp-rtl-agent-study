"""Run one ACE-RTL attempt on the locked CVDP task."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
ace = root / ".local/upstream/ace"
venv = ace / ".cvdp-native/bin"
sim = root / ".local/tools/icarus-verilog/13.0/bin"
lock = json.loads((root / "experiments/P0/lock.json").read_text())
data = ace / "datasets" / lock["dataset"]["file"]
if hashlib.sha256(data.read_bytes()).hexdigest() != lock["dataset"]["sha256"]:
    raise SystemExit("dataset does not match the P0 lock")
task = lock["first_task"]["id"]
key = os.environ.get("DEEPSEEK_API_KEY")
if not key:
    raise SystemExit("DEEPSEEK_API_KEY is missing")

os.umask(0o077)
output = ace / "outputs"
output.mkdir(exist_ok=True)
run = Path(tempfile.mkdtemp(prefix="p1-", dir=output))
print(run, flush=True)
model = "deepseek-flash"
env = {
    "PATH": os.pathsep.join(map(str, (venv, sim, "/usr/bin", "/bin"))),
    "HOME": str(run),
    "LANG": "en_US.UTF-8",
    "DEEPSEEK_API_KEY": key,
    "ACE_RTL_LLM_SCRIPT": str(root / "scripts/deepseek_adapter.py"),
    "P1_TRACE_DIR": str(run / "api"),
    "CVDP_NATIVE_HARNESS": "1",
    "ACE_RTL_DISABLE_EDA_SETUP": "1",
    "ACE_RTL_STREAM": "0",
    "ACE_RTL_ENABLE_REASONING": "0",
    "ACE_RTL_MAX_TOKENS": "4096",
    "ACE_RTL_LLM_TIMEOUT": "100",
}
command = [
    str(venv / "python"), "skills/ace-rtl/scripts/ace_cvdp_native_runner.py",
    "--workspace", str(ace), "--cvdp-repo", str(ace / "external/cvdp_benchmark"),
    "--dataset", str(data), "--cid", "cid016", "--id", task, "--outputs-root", str(run),
    "--generator-model", model, "--reflector-model", model, "--coordinator-model", model,
    "--attempts", "1", "--datapoint-workers", "1", "--max-iterations", "1",
    "--llm-timeout", "110", "--evaluator-timeout", "60",
]
(run / "command.json").write_text(json.dumps(command, indent=2))
with (run / "console.log").open("w") as log:
    result = subprocess.run(command, cwd=ace, env=env, stdout=log, stderr=subprocess.STDOUT)
raise SystemExit(result.returncode)

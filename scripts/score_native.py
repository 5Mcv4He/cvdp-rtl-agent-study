"""Run the CVDP CLI with ACE-RTL's native service runner on this host."""
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
cvdp = root / ".local/upstream/cvdp"
ace_scripts = root / ".local/upstream/ace/skills/ace-rtl/scripts"
runner = cvdp / "run_benchmark.py"
sys.path[:0] = [str(cvdp), str(ace_scripts)]
from ace_cvdp_native.harness import install_native_harness_patch

install_native_harness_patch()
os.chdir(cvdp)
sys.argv = [str(runner), "--external-network", *sys.argv[1:]]
runpy.run_path(str(runner), run_name="__main__")

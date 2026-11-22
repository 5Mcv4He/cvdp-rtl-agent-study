#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ace="$PWD/.local/upstream/ace"
if [[ ! -d "$ace" ]]; then
  bash scripts/setup_pilot_mac.sh
fi

patch_file="$PWD/patches/ace-study.patch"
if ! git -C "$ace" apply --reverse --check "$patch_file" 2>/dev/null; then
  git -C "$ace" apply "$patch_file"
fi

export UV_CACHE_DIR="$PWD/.local/uv-cache"
if [[ ! -d .local/dsh-venv ]]; then
  uv venv --python 3.12.13 .local/dsh-venv
fi
uv pip sync --python .local/dsh-venv/bin/python experiments/P2/dsh-requirements.txt

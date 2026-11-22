#!/bin/bash
# Prepare a fresh macOS arm64 workspace using project-local paths.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

# Preserve any existing setup and experiment data.
for path in .local/upstream .local/tools .local/score; do
  if [[ -e "$path" ]]; then
    echo "$path already exists. Use a fresh checkout for a clean setup." >&2
    exit 1
  fi
done

mkdir -p .local/upstream .local/tools .local/data
export UV_CACHE_DIR="$PWD/.local/uv-cache"
fetch() {
  local url="$1" dest="$2" sha="$3"
  curl -fLsS --retry 2 --max-time 120 "$url" -o "$dest"
  printf '%s  %s\n' "$sha" "$dest" | shasum -a 256 -c
}

upstream="$PWD/.local/upstream"
ace="$upstream/ace"
cvdp="$upstream/cvdp"
fetch https://codeload.github.com/NVlabs/ACE-RTL/tar.gz/94754d796350d42502c9a32639a20d86f50e9678 "$upstream/ace.tgz" dc78cb5c7565256eac5891e9dd4f7936100cca0172b459ec29618c540e3fc4c5
fetch https://codeload.github.com/NVlabs/cvdp_benchmark/tar.gz/8e894cf74414ab1eaea1e2b4e80a02f123df07b6 "$upstream/cvdp.tgz" d2acf435e9e0c9c3cb6bdeec0a7fe80d4c55bb7c647e38a35ba2b185a582ab59
mkdir -p "$ace/external" "$ace/datasets" "$cvdp"
tar -xzf "$upstream/ace.tgz" -C "$ace" --strip-components=1
tar -xzf "$upstream/cvdp.tgz" -C "$cvdp" --strip-components=1
cp -R "$cvdp" "$ace/external/cvdp_benchmark"
git -C "$ace" apply "$PWD/patches/ace-p1.patch"

data=cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl
fetch "https://huggingface.co/datasets/nvidia/cvdp-benchmark-dataset/resolve/5b807d945f6a99aa645f7e43a64a2115e281b4bf/$data" ".local/data/$data" cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857
cp ".local/data/$data" "$ace/datasets/"

bottle=0c26b4d54f2a1264a7b9105345192f303ffaa79e7e164cf705baa3c2df275871
curl -fLsS --max-time 60 -H 'Authorization: Bearer QQ==' \
  "https://ghcr.io/v2/homebrew/core/icarus-verilog/blobs/sha256:$bottle" -o .local/tools/iverilog.tgz
printf '%s  %s\n' "$bottle" .local/tools/iverilog.tgz | shasum -a 256 -c
tar -xzf .local/tools/iverilog.tgz -C .local/tools

uv venv --python 3.11.15 "$ace/.cvdp-native"
uv pip sync --python "$ace/.cvdp-native/bin/python" experiments/P1/ace-requirements.txt
uv venv --python 3.12.13 .local/score
uv pip sync --python .local/score/bin/python experiments/P1/score-requirements.txt

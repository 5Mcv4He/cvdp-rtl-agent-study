# P0 调查记录 · 2026-11-22
1. 用 uname、sw_vers、sysctl、df、command -v、uv python list --only-installed 和 utmctl list 盘点本机；按既有 SSH 配置尝试连接，端口拒绝，UTM 确认虚拟机关机。上次来宾实测与本次主机结果分别列在 environment.md。系统软件安装 0。
2. 用浅克隆读取三个上游的默认分支 HEAD，以 git rev-parse HEAD 获取 SHA；用 git ls-tree、官方 GitHub 文件接口和定向读取核查运行循环、provider、评分和 SDK。调研用临时源码目录不作为项目依赖。workspace 的 check-existing.sh 搜到 NVIDIA 的 ACE-RTL（当时 50 stars）；本项目复用它，独立仓库用于对照协议和轨迹证据。
3. 获取 HF 数据集元数据、固定 revision 的 JSONL；按行解析，得到 lock.json 的条数、分类、文件路径、文件和首题原始行 SHA256。原始 JSONL 放在 .local/data/，Git 忽略，可按下面的命令重取。example_dataset 的 v1.1.0 非商业有解样例只有一行 cid003 LFSR。检查首题 pytest/cocotb 代码，识别有断言的固定向量及无数值断言的随机循环。此步骤没有运行仿真。
4. 仅向 api.deepseek.com 发认证 GET /models，返回 200，ID 为 deepseek-flash、deepseek-v4-pro。没有保存认证头。用固定版本 llm_backend.py 导入 LLMBackend，对上述两个名称分别调用构造器，均在本地报 ValueError，正文为 Only NVIDIA Inference API models are supported by the built-in backend。未调用生成接口。组件路由判断来自构造测试及源码调用链，不是整轮运行结果。
5. 阅读 CVDP 与 ACE 论文、NVIDIA 模型对照报告、CVDP 数据卡和固定源码。将官方对比数字与实测调查分列。创建本地 Git 仓库和工作区导航，保存部署、协议、操作方案与版本。无外部发布。

复核数据可从项目根目录运行：
```bash
mkdir -p .local/data
f=cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl
curl -fLsS "https://huggingface.co/datasets/nvidia/cvdp-benchmark-dataset/resolve/5b807d945f6a99aa645f7e43a64a2115e281b4bf/$f" -o ".local/data/$f"
shasum -a 256 ".local/data/$f"
python3 - <<'PY'
import json, hashlib
from pathlib import Path
m = json.loads(Path("experiments/P0/lock.json").read_text())
d = m["dataset"]
b = (Path(".local/data") / d["file"]).read_bytes()
assert hashlib.sha256(b).hexdigest() == d["sha256"]
rows = list(map(json.loads, b.splitlines()))
r = m["first_task"]
line = b.splitlines()[r["line_1based"] - 1]
assert hashlib.sha256(line).hexdigest() == r["row_sha256_without_newline"]
assert json.loads(line)["id"] == r["id"]
print(len(rows), sum("cid016" in row["categories"] for row in rows), r["id"])
PY
```

# 固定 ACE-RTL 比较 Claude、GPT 和 DeepSeek

这个对照用同一个 ACE-RTL 流程解 CVDP 数字逻辑调试题。每道题给模型一份有缺陷的 RTL。ACE-RTL 生成候选，运行仿真，必要时结合精简反馈再修一轮。CVDP 原测试评分，候选另行独立重放。

## 单题接入验证

在单独的 32 位 Brent–Kung 加法器题上，两款模型均在首轮得到通过仿真的修复。额外用 32 组进位边界和 4,096 组固定种子的随机输入，对照 33 位行为加法检查低 32 位和进位。该加法器题单独报告。 [单题数据](cross-provider-pilot.json) · [算术检查脚本](../../scripts/check_adder_arithmetic.py)

| ACE-RTL 使用的模型 | CVDP 原测试 | 模型请求 | 独立算术检查失配 |
|---|---:|---:|---:|
| Claude Opus 5.5 | 首轮通过 | 1 | 0/4,128 |
| GPT-6.2 Astra | 首轮通过 | 1 | 0/4,128 |

## 完整对照的条件

两款新模型复用四组对照里的 12 道题和两次重复。ACE-RTL 的角色提示、精简反馈、两轮和四个模型请求的上限一致。每个请求沿用 48,000 字节输入上限和 4,096 输出 token 上限。新的两个配置通过米醋外接渠道调用，用响应中的模型 ID 核对每次请求，推理强度参数均为 `low`。DeepSeek 的两个冻结基线走官方接口并关闭思考。 [新批次配置](cross-provider-design.json) · [原对照](factorial-report.md) · [米醋外接说明](https://docs.micuapi.ai/external-compat)

模型、API 渠道、采样参数和推理设置共同构成这里的实验配置。相同输出 token 上限在不同接口上可包含不同数量的推理 token。分批运行及渠道差异也限制了归因。比较适用于这 12 道题的实际配置。

完整批次正在采集。

## 复现

通过运行环境提供 `MICU_CLAUDE_API_KEY`（`vip_1_max_ext`）和 `MICU_CODEX_API_KEY`（`vip_2`）。同一份本地配置可用于单题和批量，脚本只将对应凭据传入角色模型请求链。

```bash
bash scripts/setup_study_mac.sh
python3 scripts/run_ace_study.py --model claude-opus-5-5 --compact --calls 4
python3 scripts/run_ace_study.py --model gpt-6.2-astra --compact --calls 4
python3 scripts/run_suite.py --design experiments/suite/cross-provider-design.json \
  --workers 4 --confirmed-budget-usd 160
```

该批次最多安排 192 次模型请求。预算参数检查的是按官方价目计算的计划预留金额，米醋账单以其账户用量为准。运行目录含完整请求和响应，应保留在本地。 [Claude 价目](https://platform.claude.com/docs/en/models/opus-5-5/overview) · [GPT 价目](https://developers.openai.com/api/docs/models/gpt-6.2-astra)

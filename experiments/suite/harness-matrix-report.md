# 两个 Agent × 四款模型的 RTL 调试对照

每次给 Agent 一道 CVDP 数字逻辑调试题和一份有缺陷的 RTL，使用原测试评分。12 道题各运行两次。ACE-RTL 组织生成和反思角色，DeepSeek Harness（DSH）在关闭工具的 SDK 会话中生成候选并接收外部仿真结果。两边最多提交两份候选。所有候选都在同一套测试下重放。

## 结果

下表覆盖全部 8 个组合，共 192 次正式运行。每项通过数的分母为 24。 [逐题结果与配对统计](harness-matrix-results.json)

| Agent | 模型 | 首份候选通过 | 两次请求内通过 | 最终通过 | 观测请求 |
|---|---|---:|---:|---:|---:|
| ACE-RTL | DeepSeek Flash | 7/24 | 7/24 | 12/24 | 71 |
| ACE-RTL | DeepSeek V4 Pro | 5/24 | 5/24 | 11/24 | 77 |
| ACE-RTL | Claude Opus 5.5 | 24/24 | 24/24 | 24/24 | 28 |
| ACE-RTL | GPT-6.2 Astra | 22/24 | 22/24 | 22/24 | 30 |
| DSH（关闭工具） | DeepSeek Flash | 7/24 | 10/24 | 10/24 | 41 |
| DSH（关闭工具） | DeepSeek V4 Pro | 10/24 | 12/24 | 12/24 | 38 |
| DSH（关闭工具） | Claude Opus 5.5 | 21/24 | 21/24 | 21/24 | 25 |
| DSH（关闭工具） | GPT-6.2 Astra | 16/24 | 20/24 | 20/24 | 32 |

- Claude 和 GPT 在两种 Agent 中的最终通过数均高于各自的两个 DeepSeek 配置。换 Agent 后，Claude 少通过三次，GPT 少通过两次。这两个差值都按相同题目与重复编号核对过。
- 对同一个 GPT，ACE 首份候选通过 22 次，DSH 首份候选通过 16 次，差距为 6 次。DSH 在状态机和行缓冲两道题上各有 2 次靠第二轮修回，最终差距缩小至 2 次。
- DSH 的 Claude 有两次在咖啡机题触发 4,096 输出 token 上限，均未交付可评分候选。另一项失败是等差数列题的功能检查。区分未提交与功能失败可以看清通过率损失发生在哪一步。

## 新增的两组

DeepSeek Harness 通过原生供应商插件连接米醋。Claude 使用 Anthropic Messages，GPT 使用 OpenAI Responses。与 ACE-RTL 的对应两组共用令牌分组，推理强度都设为 `low`。DeepSeek 的两种模型沿用官方接口和关闭思考的设置。SDK 的系统提示、消息和缓存策略随 Agent 实现，含义相同的推理强度参数也可对应不同计算量。 [新增配置](harness-matrix-design.json) · [DSH SDK](https://github.com/deepseek-ai/deepseek-harness/blob/d98f5d68519215da48f3002da2cb9c9d2068d81d/python/sdk/README.md)

单独的 Brent–Kung 加法器接入验证中，两款模型经 DSH 都用一次请求通过 CVDP 原测试，额外 4,128 组固定种子和边界输入均零失配。加法器接入验证排在 12 题之外。 [独立检查脚本](../../scripts/check_adder_arithmetic.py)

SDK 在配置变动时才重发模型配置事件。批次初始校验误把 9 次第二轮中的正常省略视为异常。修正校验后，从原记录提取对应候选并独立仿真，模型请求均来自原批次。这 9 次标注 `offline_replay`，耗时字段留空。 [逐题结果](harness-matrix-results.json)

## 适用范围

这套矩阵覆盖两种现有 Agent 配置和四个模型的全部组合。每组使用同一批题、初始 RTL 和评分测试。ACE-RTL 和 DSH 分别最多发起四次和两次模型请求，所以同时报告两次请求内和各流程最终的结果。DSH 的请求数取自 SDK 事件，ACE 新增模型组的账本包含连接中断和截断后的重试。

各组先后运行，API 协议、提供方、系统提示、缓存和推理设置均可影响分数。12 道题来自同一 CVDP 类别，DSH 关闭文件和命令工具，这些试次测的是受控环境下的求解表现。工具开启、统一总 token 或墙钟预算，以及独立保留验收测试，仍是各自独立的实验问题。 [实验协议](../../docs/protocol.md)

## 复现新增两组

在本地环境提供 `MICU_CLAUDE_API_KEY`（`vip_1_max_ext`）和 `MICU_CODEX_API_KEY`（`vip_2`）。批次的请求上限为 96，预算参数用于按公开价目做计划检查。

```bash
bash scripts/setup_study_mac.sh
.local/dsh-venv/bin/python scripts/run_suite.py \
  --design experiments/suite/harness-matrix-design.json --workers 4 --confirmed-budget-usd 80
```

将 `STUDY_RESULTS` 设为新运行目录中 `results.json` 的路径，再对齐发布的两个基线。保持私有运行目录在本地。

```bash
python3 scripts/summarize_study.py experiments/suite/factorial-results.json \
  --harness-matrix-with experiments/suite/cross-provider-results.json "$STUDY_RESULTS"
```

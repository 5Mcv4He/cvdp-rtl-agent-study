# 补齐 Agent × 模型的四组对照

原来的三组回答了两个问题。固定 ACE-RTL 时可以比较 Flash 和 V4 Pro，固定 Flash 时可以比较 ACE-RTL 和 DSH。补齐 **DSH ＋ V4 Pro** 后，可以分别在两个 Agent 内比较模型，也可以分别固定两个模型比较 Agent。这让我们看到同一次模型切换在不同流程里的表现。

## 四组实测结果

| 配置 | 首次通过 | 两次请求内通过 | 流程结束时通过 | 观测请求数 |
|---|---:|---:|---:|---:|
| ACE-RTL ＋ DeepSeek Flash | 7/24 | 7/24 | 12/24 | 71 |
| ACE-RTL ＋ DeepSeek V4 Pro | 5/24 | 5/24 | 11/24 | 77 |
| DSH ＋ DeepSeek Flash（关闭工具） | 7/24 | 10/24 | 10/24 | 41 |
| DSH ＋ DeepSeek V4 Pro（关闭工具） | 10/24 | 12/24 | 12/24 | 38 |

新增的 24 次都有候选评分和使用量记录，24 个首轮 SDK 事件均显示 `deepseek-v4-pro` 及关闭思考。第四组按峰时价估算约 0.189 美元，按实验当天非高峰费率估算约 0.095 美元。 [四组逐题数据与配对统计](factorial-results.json) · [定价来源](https://api-docs.deepseek.com/quick_start/pricing/)

- **固定 DSH 更换模型。** Pro 首次多通过 3 次，最终多通过 2 次。按任务与重复编号配对，最终有 6 对只有 Pro 通过，4 对只有 Flash 通过，另有 6 对同过、8 对同未过。
- **固定 V4 Pro 更换 Agent。** DSH 两次请求内通过 12 次，ACE 通过 5 次。各自流程结束后，通关数为 12 次与 11 次。最终 5 对只有 DSH 通过，4 对只有 ACE 通过。
- **模型切换的方向随配置而异。** 流程结束时，Pro 相对 Flash 在 ACE 中少通过 1 次，在 DSH 中多通过 2 次。两个变化相差 3/24，约 12.5 个百分点。这是描述性差值，样本量及补跑顺序限制了归因。

## 比较条件

第四组与原有 DSH ＋ Flash 采用相同的 SDK 版本、无工具配置、公开任务输入、关闭思考模式、两轮上限和外部评分反馈。12 道题各运行两次，每组的 24 个任务与重复编号一一对应。评分使用同一套 CVDP 原测试。ACE 的第二次生成常要经过额外反思请求，因此同时报告首次、最多两次观测请求和各自流程结束三个口径。 [任务配置](factorial-design.json) · [原三组研究方法](report.md)

第四组在同一机器上单独补跑，保留前三组的原始记录。四组覆盖了两个因素的全部组合，运行时间与批次顺序仍可能影响模型服务、缓存和耗时。这里报告的是这批题目上的观察，不能仅凭差值确认普遍的架构与模型交互效应。DSH 的两组均关闭工具，结果不覆盖工具开启的配置。

## 复现第四组

```bash
bash scripts/setup_study_mac.sh
.local/dsh-venv/bin/python scripts/run_suite.py \
  --design experiments/suite/factorial-design.json --condition dsh-pro \
  --confirmed-budget-usd 4 --workers 3
```

脚本从本地环境读取 `DEEPSEEK_API_KEY`，将私有运行目录打印到终端。全四组重跑时可省去 `--condition`，并将预留预算调至 15 美元。模型输出可能随运行变化。

# RTL Agent Study

给 AI 一段有缺陷的芯片逻辑，它在哪里失败，原因能否查清，又能否把这个问题做成可靠的训练任务？这个项目从 RTL 调试实验出发，研究大模型后训练需要的任务、环境与反馈。RTL 是描述芯片数字逻辑的代码，本项目从一个 32 位加法器开始。

**当前阶段：V2 D2 奖励质量实测（2026-11-22）**　为 Brent–Kung 加法器和 64b/66b 编码器编写独立 Verifier。它们检出全部 9 种定向功能变异，CVDP 原测试检出 6 种；两边都接受 4 份正确对照。结果支持离线功能验收，接入 Agent 强化学习前还需独立终评和评分隔离。 [Reward Quality Report](docs/reward-quality-report.md) · [D0 / D1 实测](docs/d0-d1-report.md) · [V2 方法](docs/methodology-v2.md)

后续产出分为行为数据、能力缺陷报告、RL 任务候选和奖励质量报告。优先查明失败原因及验证反馈质量，再决定是否扩大实验。下面保留 V1 结果，分数不追溯修改。

**当前结果（2026-11-22）**　同样的 12 道 CVDP RTL 调试题，每题各跑两次，覆盖 **两个 Agent × 四款模型，共 192 次运行**。DSH 关闭工具。 [八组对照报告和复现](experiments/suite/harness-matrix-report.md) · [逐题数据](experiments/suite/harness-matrix-results.json)

| 模型 | ACE-RTL 最终通过 | DeepSeek Harness 最终通过 |
|---|---:|---:|
| DeepSeek Flash | 12/24 | 10/24 |
| DeepSeek V4 Pro | 11/24 | 12/24 |
| Claude Opus 5.5 | 24/24 | 21/24 |
| GPT-6.2 Astra | 22/24 | 20/24 |

**新增：开启工具的 DSH（2026-11-22）**　此前 DSH 成绩全部关闭工具。在 Brent–Kung 加法器单题上，为关闭思考的 DSH＋Flash 新增开启工具的配置：模型在隔离工作区里用 bash 和文件读写编辑工具自查自改，允许的验证命令是 `iverilog`/`vvp`，最终评分仍走同一条 CVDP `local_import` 重放。配对结果：两侧都通过——关闭工具 1 次请求，开启工具 7 次请求（模型自建测试台并在提交前看到 `ALL PASS`）。隔离先用模拟响应验收（12 项断言：哨兵文件不可读、工作区外不可写、外网不可达、真实凭据只在回环中转层），真实运行前必须通过。 [单题配对](experiments/suite/tools-pilot.json) · [报告章节](experiments/suite/report.md)

**状态机题工具试跑**　工具运行器已进入正式题集的一道状态机调试题。两次请求的开关对照均未通过。开启工具的两次运行均触及各自请求上限，评分器重放了当时的工作区快照。 [结果与预算口径](experiments/suite/report.md#工具试跑扩展到正式题)

**12 题工具开关对照**　固定 DSH＋Flash，两组共用 8 次模型请求上限，共跑 48 次。关闭工具通过 12/24，开启工具通过 6/24。工具组另有 5 次在预算耗尽时留下了通过原测试的快照。 [通过率、预算耗尽率和完成提交率](experiments/suite/tools-suite-report.md)

一次实验由三部分组成。CVDP 提供题目、已有 RTL 和评分测试，Agent 组织生成代码与仿真反馈，底层模型给出修改。项目也对比了 ACE-RTL 和关闭工具的 DeepSeek Harness 在同题、同模型下的表现。 [CVDP](https://github.com/NVlabs/cvdp_benchmark) · [ACE-RTL](https://github.com/NVlabs/ACE-RTL) · [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)

## 如何读这些结果

- **首份候选和多轮要分开看。** DSH＋GPT 首份候选通过 16/24，第二轮多通过 4 次。Flash 模型下，两次请求内 DSH 通过 10/24，ACE 通过 7/24。ACE 允许更多角色请求后最终通过 12/24。 [八组请求口径](experiments/suite/harness-matrix-report.md)
- **模型切换的结果随流程而异。** 从 Flash 换到 Pro 后，ACE 最终少通过 1 次，DSH 多通过 2 次。第四组是单独补跑的批次，这一差值适用于当前样本。
- **通过率取决于评分测试覆盖。** 加法器题给出了全部带断言的固定向量，随机向量原本只记录输出。项目为这道题加做了独立检查。12 题对照仍采用 CVDP 原测试。
- **局限。** 样本来自一个任务类别，DSH 关闭工具，两边采用不同 API 接入和默认采样设置。结果能解释本次通过与失败的轨迹，通用排名需要更广任务和更多重复。

## 首题结果

任务是 CVDP v1.1.0 的 `cvdp_copilot_32_bit_Brent_Kung_PP_adder_0001`，属于 `cid016` 非商业 RTL 调试。采用 macOS arm64 上的 Icarus Verilog 13.0 和 cocotb 2.0.1，使用 CVDP 原测试。ACE-RTL 运行一次尝试、一轮生成，底层模型为 `deepseek-flash`，关闭思考模式。

| 送入评分的实现 | 实测结果 |
|---|---|
| CVDP 自带 LFSR 参考实现，环境正对照 | 3 个 cocotb 测试通过 |
| 加法器原始 RTL | 编译通过，第 2 个固定向量失败 |
| 独立编写的 33 位行为加法对照 | 通过 |
| ACE-RTL + DeepSeek Flash 候选 | 编译通过，第 2 个向量的进位预期为 0，实际为 1 |
| 通过 CVDP `local_import` 重放同一候选 | 受测 RTL 逐字节一致，复现进位错误 |
| 人工修正读取下标的诊断副本 | 通过同一套测试 |

ACE-RTL 向模型发出 **1 次请求**，消耗 2,840 个输入 token 和 1,328 个输出 token，请求耗时约 3.92 秒，按当日费率估算约 0.00122 美元。适配器已离线验证三个角色的路由，本次真实模型调用来自 Generator。 [结构化结果](experiments/P1/result.json) · [实验记录](experiments/P1/log.md)

### 这次实验发现了什么

- **编译成功后，仍要检查结果。** 在失败用例中，`0x7fffffff + 0x7fffffff = 0xfffffffe`，结果仍在 32 位内，进位应为 0。模型却返回了 1。它修改了进位树的循环范围，但沿用了错误的读取下标。比如 `i=2` 时，应合并上一层下标为 2 和 3 的组，候选却读取了下标 1 和 2。只修正第 3 至第 5 层的读取下标，诊断副本就通过了原测试。这个通过结果来自人工诊断，模型的首轮结果仍是失败。 [失败归因](experiments/P1/log.md#失败分析)
- **随机输入也需要检查预期结果。** 公开题面给出了检查器断言的全部 12 组固定向量。额外 10 组随机向量虽被执行，却只记录输出。这个案例能展示具体的调试失败，对未见输入和模型间能力差异的判断还需要独立测试及更多任务。 [测试审计脚本](experiments/P0/check_first_task.py) · [对照协议](docs/protocol.md)

## 多轮试验发现

Flash 在 ACE-RTL 中两轮输出了字节相同的 RTL，第二轮之前还发生了两次 Reflector 调用。Pro 和 DSH 中的 Flash 此次修正了进位树读取下标，两份候选逐字节相同。对两份修复样本另跑 4,128 组算术输入，均未检出错误。三组各只运行一次，结果适合分析失败与开销，比较能力还需要更多任务。 [结构化结果](experiments/P2/results.json)

## 研究进展

| 阶段 | 状态 |
|---|---|
| P0 · 环境与接口调查 | 完成。已锁定三个上游源码提交、数据集 revision 和首题指纹 |
| P1 · 首次端到端运行 | 完成原生运行与独立重放。Linux Compose 三项控制全部复现 |
| 多轮反馈 | 已观测 ACE 的 4 次调用、两轮提交和精简反馈。DSH 已完成受控单题 |
| 模型对照 | ACE-RTL 和关闭工具的 DSH 均完成四款模型对照 |
| Agent 对照 | 四款模型均完成 ACE 与关闭工具的 DSH 配对 |
| 工具对照 | 已完成单题验收与 12 题、每题两次的工具开关对照，共 48 次运行 |
| V2 D0 / D1 | 完成八类行为证据核验和四份固定回复的后处理对照。本轮模型请求 0 |
| V2 D2 | 两道题的独立 Verifier 完成 105 次离线评分，模型请求 0 |

## 复现

当前脚本面向 macOS arm64，依赖 Git、curl、uv 和 Python。想先确认题面和断言的覆盖关系，可以安装锁定的依赖后运行审计。审计仅静态读取数据集。

```bash
bash scripts/setup_pilot_mac.sh
python3 experiments/P0/check_first_task.py
```

要重跑一轮 ACE-RTL，请在本地环境中提供 `DEEPSEEK_API_KEY`。每次最多发出一次请求。

```bash
python3 scripts/run_pilot.py
```

`run_pilot.py` 会打印运行目录。候选文件保存在该目录下的 `candidate/rtl/brent_kung_adder.sv` 子目录中。把找到的文件路径传给 `python3 scripts/replay_pilot.py <候选RTL路径>`，即可在新目录运行 CVDP 评分并核对受测字节。重放只执行仿真。新一轮模型输出可能有变化，已测结果见上表。仓库提供脚本、版本锁和结构化结果，原始模型请求与响应保存在各自本地的运行目录。

开启工具的 DSH 单题有两步：先跑离线隔离验收（模拟响应，无付费请求），通过后才能真实运行；凭据内联传入，不写进 shell 环境。

```bash
.local/dsh-venv/bin/python scripts/run_dsh_tools_study.py --probe
DEEPSEEK_API_KEY=... .local/dsh-venv/bin/python scripts/run_dsh_tools_study.py \
  --task cvdp_copilot_32_bit_Brent_Kung_PP_adder_0001 --rounds 2 --max-requests 8
```

[版本锁](experiments/P0/lock.json) · [源码与接口说明](docs/interfaces.md) · [部署与环境](docs/environment.md) · [Linux Compose 校准](experiments/suite/compose-calibration.json) · [项目状态](STATUS.md) · [训练任务方向](docs/training-directions.md)

ACE-RTL 补丁包含来自 NVIDIA ACE-RTL 的 Apache-2.0 源码片段，许可证文本随仓库附带。 [上游许可证](THIRD_PARTY_LICENSE_ACE_RTL)

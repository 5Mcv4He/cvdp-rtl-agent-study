# RTL Agent Study

给 AI 一段有缺陷的芯片逻辑，它能找出错误并修好吗？修完以后，仿真测试又能证明什么？这个项目用可复现的 RTL 调试实验回答这些问题。RTL 是描述芯片数字逻辑的代码，本项目从一个 32 位加法器开始。

**当前进度（2026-11-22）**　已完成一个 32 位加法器的端到端试验和三组配置的单题对照。ACE＋DeepSeek Flash 两轮均编译通过但功能失败，ACE＋V4 Pro 和关闭工具的 DSH＋Flash 在这次首轮通过。五题配对试跑已完成，正在扩展到 12 题、每条件两次。 [多轮试验](experiments/P2/log.md) · [五题配对](experiments/suite/pilot.md)

一次实验由三部分组成。CVDP 提供题目、已有 RTL 和评分测试，ACE-RTL 组织模型生成代码和接收仿真反馈，DeepSeek Flash 是本次生成代码的模型。后续会换入通用 Agent DeepSeek Harness，在同题、同模型下比较求解过程。 [CVDP](https://github.com/NVlabs/cvdp_benchmark) · [ACE-RTL](https://github.com/NVlabs/ACE-RTL) · [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)

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
| P1 · 首次端到端运行 | 完成原生运行与独立重放。Linux Compose 判定一致性待验证 |
| 多轮反馈 | 已观测 ACE 的 4 次调用、两轮提交和精简反馈。DSH 已完成受控单题 |
| 模型对照 | 已完成 Flash／Pro 的加法器试跑。五题试跑已完成，12 题扩展中 |
| Agent 对照 | 已完成同模型的 ACE／DSH 单题试跑。五题试跑已完成，12 题扩展中 |

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

[版本锁](experiments/P0/lock.json) · [源码与接口说明](docs/interfaces.md) · [部署与环境](docs/environment.md) · [项目状态](STATUS.md)

ACE-RTL 补丁包含来自 NVIDIA ACE-RTL 的 Apache-2.0 源码片段，许可证文本随仓库附带。 [上游许可证](THIRD_PARTY_LICENSE_ACE_RTL)

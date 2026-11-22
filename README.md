# RTL Agent Study

在 [CVDP](https://github.com/NVlabs/cvdp_benchmark) 的芯片工程任务上，研究模型和 Agent 架构如何影响 RTL 调试结果。项目关注每轮生成的代码、仿真反馈、失败原因与求解成本。

**当前进度（2026-11-22）**　已完成环境调查和一次真实的单题实验。ACE-RTL 调用 DeepSeek Flash 生成的候选 **编译通过、功能测试失败**。独立重放复现了同一条断言。多轮反馈、DSH 接入和模型对照仍待运行。

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

模型发出 **1 次请求**，消耗 2,840 个输入 token 和 1,328 个输出 token，请求耗时约 3.92 秒，按当日费率估算约 0.00122 美元。适配器已离线验证三个角色的路由，本次真实模型调用来自 Generator。 [结构化结果](experiments/P1/result.json) · [实验记录](experiments/P1/log.md)

### 这次实验发现了什么

- **进位树错误可复现。** 模型扩大了第 3 至第 5 层的循环范围，但仍按 `i/2` 和 `i/2+1` 读取上一层。循环步长已经是 2，正确配对是 `i` 和 `i+1`。只修正读取下标，诊断副本便通过原测试。原始 Agent 成绩保留为失败。 [失败归因](experiments/P1/log.md#失败分析)
- **分数受检查器覆盖限制。** 公开题面已给出检查器断言的全部 12 组固定向量，额外 10 组随机向量只记录输出。这个案例用于验证工具链和分析失败。正式任务应具备有效的独立检查，并记录 Agent 在迭代期间能看到哪些验证反馈。 [测试审计脚本](experiments/P0/check_first_task.py) · [对照协议](docs/protocol.md)

## 研究进展

| 阶段 | 状态 |
|---|---|
| P0 · 环境与接口调查 | 完成。已锁定三个上游源码提交、数据集 revision 和首题指纹 |
| P1 · 首次端到端运行 | 完成原生运行与独立重放。Linux Compose 判定一致性待验证 |
| 多轮反馈 | 待实测 Reflector、第二轮生成和反馈可见范围 |
| 模型对照 | 计划固定 ACE-RTL、任务和评分条件，比较底层模型 |
| Agent 对照 | 计划固定底层模型，在同一批任务上比较 ACE-RTL 与 DeepSeek Harness |

## 复现

当前脚本面向 macOS arm64，依赖 Git、curl、uv 和 Python。安装脚本把锁定的依赖写入项目目录。运行首轮需要本地环境变量 `DEEPSEEK_API_KEY`，每次最多发出一次请求。

```bash
bash scripts/setup_pilot_mac.sh
python3 experiments/P0/check_first_task.py
python3 scripts/run_pilot.py
```

`run_pilot.py` 会打印运行目录。候选文件保存在该目录下的 `candidate/rtl/brent_kung_adder.sv` 子目录中。把找到的文件路径传给 `python3 scripts/replay_pilot.py <候选RTL路径>`，即可在新目录运行 CVDP 评分并核对受测字节。重放只执行仿真。新一轮模型输出可能有变化，已测结果见上表。仓库提供脚本、版本锁和结构化结果，原始模型请求与响应保存在各自本地的运行目录。

[版本锁](experiments/P0/lock.json) · [源码与接口说明](docs/interfaces.md) · [部署与环境](docs/environment.md) · [项目状态](STATUS.md)

ACE-RTL 补丁包含来自 NVIDIA ACE-RTL 的 Apache-2.0 源码片段，许可证文本随仓库附带。 [上游许可证](THIRD_PARTY_LICENSE_ACE_RTL)

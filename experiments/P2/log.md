# 加法器多轮试验 · 2026-11-22

给定同一道 Brent–Kung 加法器调试题，三组都用 DeepSeek 官方 API，关闭思考模式，并通过 CVDP 的 `local_import` 独立重放各自提交的 RTL。评分在同一个 macOS arm64 Python 3.12.13、Icarus 13.0 和 cocotb 2.0.1 环境完成，仿真随机种子固定为 20261122。

| 条件 | 最终状态 | 观测模型调用 | 独立算术检查 |
|---|---|---:|---:|
| ACE-RTL + DeepSeek Flash | 两轮均编译通过、功能失败。两版 RTL 字节相同 | 4 | 4,075 / 4,128 组不符合 33 位加法 |
| ACE-RTL + DeepSeek V4 Pro | 首轮通过 | 1 | 0 / 4,128 组不符合 |
| DSH + DeepSeek Flash，关闭工具 | 首轮通过 | 1 | 0 / 4,128 组不符合 |

独立算术检查根据规格另写，用 32 组进位链输入和 4,096 组固定种子的随机输入同时比较低 32 位与进位。它保留失败计数，未参与模型修复，也未替换 CVDP 判分。[结构化结果](results.json) · [算术检查脚本](../../scripts/check_adder_arithmetic.py)

## 为什么四次调用只得到两版代码

Flash 的调用顺序为 Generator、Reflector 内的架构规则筛选、Reflector 的调试建议、Generator。在早先的三次请求预算试跑中，最后一次生成被配额挡住。将上限改为四次后，第二轮成功返回代码，但候选哈希与第一轮一致，独立重放再次在同一条进位断言上失败。这说明仅报告迭代次数会遗漏相当部分的模型消耗，也应记录后续候选是否真的发生改变。

精简反馈条件下，两种 Agent 接收的是同一类结果消息，例如“编译并仿真成功，功能检查失败”。对 ACE 实际发出的四份请求做了检查，未发现具体进位断言。DSH 将任务和初始代码放进 SDK session，禁用 Shell、文件工具、工作目录工具、运行时自动重试和远端 Session 日志扩展。它接收由外部评分器产生的结果类别，再提交完整候选。试跑首轮通过，所以这一次未走 DSH 的二轮反馈分支。

## 这张表的适用范围

三组各只执行一次。ACE 保留专业角色和提示模板，DSH 使用 0.2.2rc2 的受控无工具配置。两组的底层 API 序列化、采样默认设置、角色提示和每轮最大请求数都有差异。ACE 用 Chat Completions 并记录实际请求参数，DSH 由官方 SDK 处理 API 请求，账本取自 SDK 的可观测使用量事件。结果适用于这三种实际配置的单题诊断，推断模型排名需更多题目和重复。

V4 Pro 和 DSH 的 Flash 此次导出了相同哈希的候选，二者都改对了第 3 至第 5 层的索引。独立算术检查扩大了输入覆盖，尚不能替代形式等价证明。测试代码和参数都在仓库中，原始生成请求、响应、候选和 Session 日志在本地保留。

## 运行

```bash
bash scripts/setup_study_mac.sh
python3 scripts/run_ace_study.py --compact --calls 4 --model deepseek-flash
python3 scripts/run_ace_study.py --compact --calls 4 --model deepseek-v4-pro
.local/dsh-venv/bin/python scripts/run_dsh_study.py
```

环境变量 `DEEPSEEK_API_KEY` 由运行者提供。脚本会打印本次私有运行目录，重放代码可用 [统一评分入口](../../scripts/study_common.py) 检查受测字节。新运行可能得到不同候选。五题配对另有 [预设任务与预算](../suite/design.json)，需要单独确认调用总预算。

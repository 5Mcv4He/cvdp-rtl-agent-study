# 研究目标

这个项目研究如何从真实 RTL 工程任务中发现大模型的能力问题，并将经过诊断的问题转化为可执行的训练任务、交互环境和可靠奖励。当前交付范围是训练前的行为记录、能力诊断、任务构造与 Reward 验证，尚未开展模型参数训练。

ACE-RTL 与 DeepSeek Harness 是观察模型行为的实验系统。后续修改服务于测量、变量控制、原因检验和环境复现。项目以诊断证据与训练任务质量衡量进展，不以优化 Agent 成功率或 Benchmark 排名作为主要目标。

当前已完成 V2 的 D0 行为证据转换和 D1 后处理对照。新付费实验、关键条件改变及系统安装需要先确认。V1 历史数据和评分保持不变。 [实测报告](docs/d0-d1-report.md) · [方法审计](docs/methodology-v2.md)

V1 八组对照覆盖 ACE-RTL 与 DeepSeek Harness 分别使用 DeepSeek Flash、DeepSeek V4 Pro、Claude Opus 5.5 和 GPT-6.2 Astra 的组合，共 192 次运行。DSH 采用关闭工具的配置。另有 48 次 DSH＋Flash 工具开关实验，两侧同为八次请求上限。各配置的预算、后处理和信息差异见 V2 审计，不能直接归因为模型能力。

首批任务来自 CVDP v1.1.0 的 Non-Agentic Code Generation / No Commercial 分区，优先选 `cid016` RTL 调试题。这里的 Non-Agentic 描述题目和交付格式，两种 Agent 都可以多轮求解。每次运行固定题目、源码版本和评分条件，记录具体的候选、诊断与判定。

已完成单题诊断、五题试跑和 12 题的八组配对分析。真实轨迹用于提出可检验的训练任务和评分方法。 [当前进度](STATUS.md) · [首题实测](experiments/P1/log.md) · [八组对照报告](experiments/suite/harness-matrix-report.md) · [实验协议](docs/protocol.md)

# 研究目标

这个项目研究 AI 如何调试数字芯片的 RTL 代码。我们观察首次生成的代码、仿真反馈、后续修复和失败原因，同时记录模型调用与验证成本。

八组对照覆盖 ACE-RTL 与 DeepSeek Harness 分别使用 DeepSeek Flash、DeepSeek V4 Pro、Claude Opus 5.5 和 GPT-6.2 Astra 的组合。分别固定 Agent 或模型比较另一项，并记录验证反馈、交付和请求预算。DSH 采用关闭工具的配置。

首批任务来自 CVDP v1.1.0 的 Non-Agentic Code Generation / No Commercial 分区，优先选 `cid016` RTL 调试题。这里的 Non-Agentic 描述题目和交付格式，两种 Agent 都可以多轮求解。每次运行固定题目、源码版本和评分条件，记录具体的候选、诊断与判定。

已完成单题诊断、五题试跑和 12 题的八组配对分析。真实轨迹用于提出可检验的训练任务和评分方法。 [当前进度](STATUS.md) · [首题实测](experiments/P1/log.md) · [八组对照报告](experiments/suite/harness-matrix-report.md) · [实验协议](docs/protocol.md)

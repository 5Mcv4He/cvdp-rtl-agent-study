# 研究目标

这个项目研究 AI 如何调试数字芯片的 RTL 代码。我们观察首次生成的代码、仿真反馈、后续修复和失败原因，同时记录模型调用与验证成本。

计划中的两组对照各改变一个主要条件。模型对照固定 ACE-RTL、任务和测试，更换底层模型。Agent 对照固定 DeepSeek 模型和推理模式，让 ACE-RTL 与 DeepSeek Harness 完成相同任务，并尽量对齐验证反馈和资源预算。

首批任务来自 CVDP v1.1.0 的 Non-Agentic Code Generation / No Commercial 分区，优先选 `cid016` RTL 调试题。这里的 Non-Agentic 描述题目和交付格式，两种 Agent 都可以多轮求解。每次运行固定题目、源码版本和评分条件，记录具体的候选、诊断与判定。

已完成单题诊断、五题试跑和 12 题的两组配对分析。真实轨迹用于提出可检验的训练任务和评分方法。 [当前进度](STATUS.md) · [首题实测](experiments/P1/log.md) · [配对报告](experiments/suite/report.md) · [实验协议](docs/protocol.md)

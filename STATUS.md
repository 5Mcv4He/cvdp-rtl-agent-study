# 状态 · 2026-11-22

- 当前阶段：Methodology V2 Audit 已完成。已定位 192 次矩阵试次的本地记录并审查 48 次工具对照，形成八类案例、三层数据设计、最小诊断实验及 RL 任务/奖励质量规范。只做离线解析与静态审查，未新增付费请求、未重跑历史评分、未实现规划功能。见 [方法审计与下一阶段计划](docs/methodology-v2.md)。
- 项目目标已明确为专业能力诊断、任务环境与反馈质量研究。后续先补齐证据链、后处理对照和 Verifier 质量检查；新增真实模型实验、关键条件变更及系统安装须先确认。以下 V1 记录保留原样。
- P0 已锁定 CVDP 数据与源码版本，完成环境和接口调查。
- P1 已跑通真实单题。ACE＋Flash 首轮编译成功并在进位断言上失败，重放复现了该断言。
- 多轮加法器试验已完成。ACE＋Flash 两轮都失败，ACE＋Pro 与 DSH＋Flash 在此次首轮通过。三组各运行一次，见 [实验记录](experiments/P2/log.md)。
- 已选定五道调试题，并验证原始 RTL 在本机均会触发功能断言。三组的五题配对试跑已完成，见 [试跑结果](experiments/suite/pilot.md)。已完成 12 题、三种配置、每题两次的扩展实验。见 [完整报告](experiments/suite/report.md)。
- Linux Compose 三项控制与本地判定一致，见 [校准结果](experiments/suite/compose-calibration.json)。四组共 96 次运行，使用统一的 macOS 原生评分。
- 长输入补充诊断复现了 8 次原先未发送的第二轮请求。8 份候选均在功能测试失败，补发结果与主实验分别保留。
- 已补齐 DSH＋V4 Pro。24 次首轮中有 10 次通过，最终通过 12 次。见 [四组对照报告](experiments/suite/factorial-report.md)。
- ACE-RTL 已完成 Claude Opus 5.5 与 GPT-6.2 Astra 的两组单题验证和 48 次配对运行。Claude 通过 24/24，GPT 通过 22/24，后者的两次失败均出现在等差数列题。 [跨模型报告](experiments/suite/cross-provider-report.md)
- 已补齐关闭工具的 DSH＋Claude 和 DSH＋GPT，共新增 48 次正式运行。最终分别通过 21/24 和 20/24。两类 Agent 配置和四款模型共 192 次运行。 [八组对照报告](experiments/suite/harness-matrix-report.md)
- 已为 DSH 新增开启工具的单题配对（Brent–Kung，Flash、关闭思考）。隔离用模拟响应验收 12 项断言，真实运行前强制通过验收门。两侧均一次提交通过：关闭工具 1 次请求，开启工具 7 次请求（含自建测试台验证）。见 [配对结果](experiments/suite/tools-pilot.json) 与 [报告章节](experiments/suite/report.md)。
- 工具运行器已通过 12 道正式题的输入预检。已修复离线隔离验收的刷新问题，并实跑状态机题的开关对照和八次请求的工具探索。 [状态机题数据](experiments/suite/tools-fsm-pilot.json)
- DSH＋Flash 工具开关正式对照已完成 48 次运行。关组通过 12/24、预算耗尽 0/24、完成提交 22/24。开组通过 6/24、预算耗尽 15/24、完成提交 10/24。 [工具开关报告](experiments/suite/tools-suite-report.md)

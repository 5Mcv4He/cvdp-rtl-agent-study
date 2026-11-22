# 状态 · 2026-11-22

- P0 已锁定 CVDP 数据与源码版本，完成环境和接口调查。
- P1 已跑通真实单题。ACE＋Flash 首轮编译成功并在进位断言上失败，重放复现了该断言。
- 多轮加法器试验已完成。ACE＋Flash 两轮都失败，ACE＋Pro 与 DSH＋Flash 在此次首轮通过。三组各运行一次，见 [实验记录](experiments/P2/log.md)。
- 已选定五道调试题，并验证原始 RTL 在本机均会触发功能断言。三组的五题配对试跑已完成，见 [试跑结果](experiments/suite/pilot.md)。已完成 12 题、三种配置、每题两次的扩展实验。见 [完整报告](experiments/suite/report.md)。
- Linux Compose 三项控制与本地判定一致，见 [校准结果](experiments/suite/compose-calibration.json)。四组共 96 次运行，使用统一的 macOS 原生评分。
- 长输入补充诊断复现了 8 次原先未发送的第二轮请求。8 份候选均在功能测试失败，补发结果与主实验分别保留。
- 已补齐 DSH＋V4 Pro。24 次首轮中有 10 次通过，最终通过 12 次。见 [四组对照报告](experiments/suite/factorial-report.md)。

# 状态 · 2026-11-22

- P0 已锁定 CVDP 数据与源码版本，完成环境和接口调查。
- P1 已跑通真实单题。ACE＋Flash 首轮编译成功并在进位断言上失败，重放复现了该断言。
- 多轮加法器试验已完成。ACE＋Flash 两轮都失败，ACE＋Pro 与 DSH＋Flash 在此次首轮通过。三组各运行一次，见 [实验记录](experiments/P2/log.md)。
- 已选定五道调试题，并验证原始 RTL 在本机均会触发功能断言。三组的五题配对试跑已完成，见 [试跑结果](experiments/suite/pilot.md)。已完成 12 题、三种配置、每题两次的扩展实验。见 [完整报告](experiments/suite/report.md)。
- Linux Compose 正反对照使用公开仓库的手动 Actions 工作流校准。结果单列，不混入 macOS 的模型成绩。

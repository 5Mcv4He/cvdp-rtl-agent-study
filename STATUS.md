# 状态 · 2026-11-22
P0 已完成，版本锁见 experiments/P0/lock.json。
P1 已完成单题原生闭环。DeepSeek Flash 发出一次生成请求，ACE 候选编译通过、功能失败。CVDP local_import 独立重放复现进位错误。第 3 到 5 层索引诊断副本通过原始测试。见 experiments/P1/log.md 和 result.json。
公开的首题检查存在覆盖局限。下一阶段验证付费的反思、重试与第二轮生成，另做官方 Compose 一致性校准；尚无 DSH 或批量对照结果。系统安装、新虚拟机或批量费用需先获用户同意。

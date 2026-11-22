# P1 单题运行 · 2026-11-22

完成一题一轮的 ACE 原生闭环。Icarus 13.0 使用已验 SHA-256 的 macOS arm64 Homebrew bottle 解包到项目目录。ACE 使用 Python 3.11.15、pytest 9.1.1，独立评分使用 Python 3.12.13、pytest 8.3.2，两者均用 cocotb 2.0.1。同版本模拟器、本地两套 Python 环境，以 ACE 原生执行器调度固定的 CVDP 测试。官方 Compose 镜像验证尚缺。

[setup_pilot_mac.sh](../../scripts/setup_pilot_mac.sh) 从固定 archive 与数据 SHA 恢复源码与工具。两份 requirements 固定本次使用的 Python 包。已在新的空目录执行安装脚本，独立重放得到相同的候选哈希和失败断言。补丁只应用于项目目录中的 ACE 副本，复用它对生成器的外部脚本契约，将 Reflector 与 Coordinator 的内部 LLMBackend 接到同一入口。仿真环境采用变量白名单；用哨兵检查模拟器环境不含 API key。Python 环境与运行目录在本机同一账户下，隔离级别适用于本轮固定任务校准。正式 DSH 运行另需执行隔离。

| 顺序 | 实际结果 |
|---|---|
| LFSR 示例参考解 | CVDP CLI golden mode，3 个 cocotb 测试通过 |
| 加法器原始负对照 | local_import，编译成功，第 2 个固定向量进位错误 |
| 根据规格写的 33 位行为加法对照 | local_import，原始测试通过 |
| 三角色路由离线探针 | 真实 llm_call.py 和角色 LLMClient 均到达离线 adapter，返回各自角色字符串。没有发生 API 请求 |
| ACE + DeepSeek Flash | 一次真实请求，response finish_reason=stop，编译成功，首轮功能失败，规则式 Coordinator 决策继续，由一轮上限终止 |
| 独立重放 | local_import 写出的 RTL 与 ACE 候选逐字节相同，复现同一断言 |
| 索引诊断 | 在候选副本中改正第 3 至第 5 层的读取下标，同一份原始测试通过。ACE 原始结果仍是失败 |

### 失败分析

生成器把循环上限扩展到各层所需的上限，但延用了上一层读取下标的除二表达式。对步长为 2 的循环，输出组号是 i/2，输入组应为 i 和 i+1；读取 i/2 和 i/2+1 会重复使用相邻组，漏算其余位段的传播与生成信号。索引诊断只更改第 3、4、5 层的读取下标。它改善了官方测试判定，尚未做形式等价或全面功能证明。结果里有编译产物、断言及前后代码差异，可用于后续反思任务。

用已有 P0 审计脚本复核发现，公开 prompt 与检查器中的 **12 组固定向量和值完全相同且顺序一致**。随机阶段执行额外 10 组输入，但无数值断言。随机种子由本轮 runner 自动产生，日志有记录。首个失败发生在固定向量，与随机种子无关。通过此题主要意味着满足公开样例的功能行为，正式能力评估应另挑有独立有效检查的任务。

### 运行和复查

从项目根目录运行以下命令。第一条创建新运行目录，最多发一次真实请求，密钥由环境提供。第二条重放本次候选，不调用模型。
```bash
python3 scripts/run_pilot.py
python3 scripts/replay_pilot.py .local/p1/candidate.sv
```

原始运行在 `.local/upstream/ace/outputs/p1-kema_5bp/`，其中 `command.json` 是实际启动命令，`api/` 是严格裁剪后的请求和响应，`console.log` 及其生成的 run 目录包含候选、后处理、工具、评分和 Coordinator 决策。ACE 内置通用脚本的 stdout 有 provider 标签 nvidia，这是参数默认值，实际 HTTP 目的端和模型以 api/ 中的记录为准。未发现完整 checker 源码进入 Generator 消息，且本轮扫描的文本产物没有字面密钥。后续多轮另行检查失败诊断的可见范围。

`.local/p1/` 保存正反对照、独立重放、`ace-vs-initial.diff` 与 `diagnostic.diff`。所有原始实验产物均由 Git 忽略。未取得发票，以 2026-11-22 周日 DeepSeek 公布的 Flash 非高峰费率估算 0.0012228 美元。下阶段可固定上限重新测反馈回路，验证 Reflector 的实际付费调用及第二次生成、统计截断和重试；然后再估算五题费用。DSH 集成及两组对照留在后续阶段。

[机器可读结果](result.json) · [DeepSeek 模型费率](https://api-docs.deepseek.com/quick_start/pricing/)

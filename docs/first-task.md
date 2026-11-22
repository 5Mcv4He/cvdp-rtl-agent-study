# P1 首题工作单
首题选公开文件中第一个 cid016，单一目标 rtl/brent_kung_adder.sv，题号见下。任务要求修复 32 位加法器，包含输入进位、低 32 位和输出进位。input.context 给出待修 RTL。src/.env 指向 icarus，test_runner.py 调 cocotb runner 编译仿真。检查器对固定向量的 sum 和 carry_out 断言，后段 10 组随机向量只记日志，无数值断言。通过该 harness 能说明达到官方检查；若声称设计结构或更广输入正确，需另有证据。首题有公开问题描述和已知失败示例，记录哪些预期值本来就在 prompt 中。

**先验收裁判，零生成调用。** 在有 Docker Compose 的现代 Linux 执行机准备 lock.json 指定的 CVDP checkout，建立独立 Python 3.12 环境，按 requirements 安装并准备 .env；记录架构、运行库版本和镜像 digest。以下命令从 CVDP 仓库根目录执行，是锁定源码中核对过的 P1 操作方案，P0 未执行。
```bash
docker build -f docker/Dockerfile.sim -t nvidia/cvdp-sim:v1.0.0 .
python run_benchmark.py -f example_dataset/cvdp_v1.1.0_example_nonagentic_code_generation_no_commercial_with_solutions.jsonl -i cvdp_copilot_lfsr_0001 -t 1 -p work-positive
```
该示例确有参考答案，用于工具链正对照。所选 HF 分区 35 个 cid016 的 output 内容全为空。随后将首题原始 RTL 作为负对照，再用根据规格独立编写的 33 位加法行为对照检查接口、进位与评分；它只在评测侧使用，标作自建对照。预期负例能编译后在功能测试失败，行为对照通过；若实际不符，先分析 runner、断言、抽取或规格。保留官方报告、日志，并对同一候选比较 native 与容器判定。未对齐时分别报告。

**候选重放。** 官方支持 `-l -m local_import --prompts-responses-file FILE`，本地导入器读取含 id 和 completion 的 JSONL。以单一目标的 RTL 构造导入文件后，检查实际被测文件字节确实匹配提交；注意 Markdown 代码块抽取规则。若导入失败先查适配格式。给两系统的候选使用同一入口。
```bash
python run_benchmark.py -f "$DATASET" -i cvdp_copilot_32_bit_Brent_Kung_PP_adder_0001 -l -m local_import --prompts-responses-file "$ANSWERS" -t 1 -p "$FRESH_WORK"
```

**再验收路由。** 单独装 ACE 的 Python 3.11 环境，源码、CVDP 子 checkout、数据、输出按固定 SHA 放在 ACE 工作根内（runner 对路径做 ensure_under 检查），避免默认下载脚本浮动到最新。把适配器放在受信任侧；最小改动让 Generator 脚本和组件 LLMBackend 都能到达相同 DeepSeek 服务。用无费用调用探针验证三个角色及重试分支的模型名和请求格式；探针结果仅作接口测试。随后一次真实请求验收计量、超时和外显输出。P0 仅验证模型列表，建议 P1 首次使用 deepseek-flash，届时复核实际响应 ID；模型服务不暴露不可变版本时保留运行时间。不同供应商的额外推理字段要显式映射并检查接受情况。

以下为完成路由适配及依赖安装后的首题命令。从 ACE 根目录运行，DATASET 指向该根目录内固定的 JSONL。ACE_RTL_LLM_SCRIPT 必须指向届时已验收的可执行适配器。
```bash
export CVDP_NATIVE_HARNESS=1
MODEL=deepseek-flash
.cvdp-native/bin/python3 skills/ace-rtl/scripts/ace_cvdp_native_runner.py \
  --workspace "$PWD" --cvdp-repo "$PWD/external/cvdp_benchmark" \
  --dataset "$DATASET" --cid cid016 --id cvdp_copilot_32_bit_Brent_Kung_PP_adder_0001 \
  --generator-model "$MODEL" --reflector-model "$MODEL" --coordinator-model "$MODEL" \
  --attempts 1 --datapoint-workers 1 --max-iterations 1
```
第一轮验收真实候选、实际模型调用账本、编译/仿真及统一评分。通过即记录首次成功；失败也作为有效产物。再用一次有预算的多轮运行观察反思分支。进入五题前，用单题实测 input/output/cache、调用次数和实际费率估算期望成本与硬上限，向用户呈报。首个 DSH 任务复用完全相同的题目与验收器。

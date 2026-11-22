# 环境调查 · 2026-11-22

下表记录 P0 开始时的状态。后续使用项目内的原生 Icarus 13.0 和 cocotb 完成了 72 次配对，用 GitHub Actions 的 Linux runner 复现三项控制。 [当前结果](../experiments/suite/report.md) · [容器校准](../experiments/suite/compose-calibration.json)
| 位置 | 实测 | 对研究的影响 |
|---|---|---|
| Mac mini | macOS 26.6.2 arm64，10 核，16 GiB 内存；内部可用 15 GiB，外接 SSD 可用 11 GiB | 适合单题串行、远端推理。镜像构建峰值与轨迹增长需实测，不能据空闲量承诺全量运行 |
| 本机工具 | Git 2.50.1、Apple clang 21、GNU Make 3.81、Node 24.14.1、uv 0.11.13。默认 Python 3.14.5；uv 已有 3.11.15、3.12.13 | ACE 首选 3.11.15；官方 CVDP 主控推荐 3.12；DSH 单独环境 |
| 可执行文件 | PATH 未见 docker、docker-compose、vvp、iverilog、verilator、yosys、cocotb-config、dsh；默认 Python 查不到 cocotb 或 deepseek_harness | 两个实验尚未就绪；无法验证 Compose 插件、模拟器调用和 DSH 运行 |
| UTM | 两台 VM 均处于 stopped，CentOS 的 SSH 连接被拒绝 | 本轮未开机。上次实测 CentOS 7.9 x86_64，2 核、4 GB、Python 3.6.8，VCS 小仿真通过。有历史记录的商业环境留作按需波形调试 |
| 远端推理 | 官方 GET /models 返回 HTTP 200，列出 deepseek-flash 和 deepseek-v4-pro；Kimi 凭据变量名存在 | 仅验证 DeepSeek 服务发现。余额、实际生成、推理参数、缓存计量、版本漂移以及其他模型可用性待测 |

**部署决策。** 首先在 Mac 用用户级 uv 环境准备题目，在隔离的无凭据执行环境运行 Icarus 13 和 cocotb 2.0.1。P1 可先用独立 macOS 用户目录前缀编译 Icarus 做小规模原生校准（与 DSH shell 的权限隔离另计）；本地依赖不兼容时优先在现代 Linux runner 上复核。不必为一题预装全套 EDA。正式两实验优先使用同一台现代 Linux＋Docker Compose 执行机；有现成远端即可使用，若使用本机 Linux 容器后端，先确定磁盘容量、平台支持并征得系统安装许可。固定镜像 digest、架构、构建依赖和冷/热启动条件。Mac 负责管理和分析，模型走远程 API，无本地 GPU 依赖。原生校准和容器评分分别保留标签。

ACE 的 native runner 会重写路径、替换 harness 执行方法，进程追踪也使用 Linux /proc。Mac 兼容性是待测假设。ACE 的 requirements 固定 pytest 9.1.1，CVDP 官方评分镜像固定 8.3.2；ACE 固定 pydantic 2.10.6，DSH SDK 源码要求 >=2.12。将 ACE、DSH、评分环境分别锁定。无凭据仿真和独立进程/容器比分开安装 Python 包多了一层权限边界。

来源：[ACE 依赖](https://github.com/NVlabs/ACE-RTL/blob/94754d796350d42502c9a32639a20d86f50e9678/requirements.txt) · [评分镜像](https://github.com/NVlabs/cvdp_benchmark/blob/8e894cf74414ab1eaea1e2b4e80a02f123df07b6/docker/Dockerfile.sim) · [DSH SDK 依赖](https://github.com/deepseek-ai/deepseek-harness/blob/d98f5d68519215da48f3002da2cb9c9d2068d81d/python/sdk/pyproject.toml)

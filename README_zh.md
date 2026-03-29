# serverHeartbeat

**语言: [English](README.md) | [中文](README_zh.md)**

一个面向 Arch Linux 服务器的高可靠性心跳记录程序。它定期将 UTC 墙上时间、单调递增时间和 Linux 启动 ID 写入结构化 JSON Lines (JSONL) 文件，从而实现精确的运行时间追踪、异常关机检测和系统时间跳变监控。

## 目录

- [设计动机](#设计动机)
- [功能特性](#功能特性)
- [项目架构](#项目架构)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
- [使用方法](#使用方法)
- [日志格式](#日志格式)
- [启动分析](#启动分析)
- [systemd 集成](#systemd-集成)
- [开发](#开发)
- [许可证](#许可证)

## 设计动机

标准的系统日志设施（systemd journal、syslog）在意外断电时可能丢失记录。本工具通过维护独立的只追加（append-only）日志文件来弥补这一缺陷——每次写入后均在同一文件描述符上调用 `os.fsync()`，确保数据在程序继续执行前已落盘。通过将墙上时钟时间戳与单调时钟读数及内核启动 ID 相结合，本工具提供了一条可靠的服务器可用性时间线，能够经受时钟调整、NTP 校时步进和非正常关机等场景的考验。

## 功能特性

- **周期性心跳记录**，间隔可配置（默认 60 秒）。
- **结构化 JSONL 输出**——每行一个 JSON 对象，便于标准工具解析。
- **fsync 持久化保证**——每次写入后在同一文件描述符上调用 `os.fsync()`，确保数据到达稳定存储介质后程序才继续执行。
- **异常关机检测**——启动时分析器检查上一次运行是否记录了 `SHUTDOWN` 事件。若缺失，则表明发生了断电、内核崩溃或其他非正常终止。
- **基于单调时钟的运行时间计算**——`time.monotonic_ns()` 不受墙上时钟调整影响，即使 NTP 校正了系统时钟也能提供精确的运行时间数据。
- **系统时间跳变检测**——比较相邻心跳之间墙上时钟增量与单调时钟增量的差异，超过可配置阈值的偏差将被标记。
- **优雅关机处理**——捕获 `SIGTERM` 和 `SIGINT` 信号，在进程退出前记录 `SHUTDOWN` 事件，从而明确区分正常关机与异常终止。
- **按天日志轮转**——心跳条目写入按日期命名的文件（`heartbeat_YYYY-MM-DD.jsonl`），每个 UTC 日一个文件。
- **零运行时依赖**——整个应用仅使用 Python 标准库。

## 项目架构

```
serverHeartbeat/
├── heatbeat.py            # 主入口：信号处理、启动分析、心跳循环
├── heartbeatConfig.py     # 常量、环境变量覆盖、系统辅助函数
├── heartbeatIO.py         # fsync 安全 JSONL 写入、健壮 JSONL 读取、文件发现
├── heartbeatAnalyzer.py   # 上次运行分析：运行时间、关机类型、时间跳变检测
└── heartbeatLog/          # 运行时创建
    ├── events.jsonl           # 生命周期事件：START、SHUTDOWN、ANALYSIS
    └── heartbeat_YYYY-MM-DD.jsonl  # 每日心跳记录
```

| 模块 | 职责 |
|---|---|
| `heartbeatConfig.py` | 集中管理所有可调常量（`LOG_DIR`、`HEARTBEAT_INTERVAL`、`TIME_JUMP_THRESHOLD`），并提供读取启动 ID、生成 ISO-8601 时间戳和查询 `CLOCK_MONOTONIC` 的底层辅助函数。 |
| `heartbeatIO.py` | 提供 `safeAppendJson()`：以 `O_APPEND` 方式打开文件，写入序列化的 JSON 行，在同一 fd 上调用 `os.fsync()`，然后关闭。同时提供健壮的 JSONL 读取器，自动跳过损坏行而不崩溃。 |
| `heartbeatAnalyzer.py` | 每次启动时定位上一个 `START` 事件，收集共享同一 `bootId` 的所有心跳，从单调时间戳计算运行时间，估算关机时间窗口，并扫描墙上时间跳变。 |
| `heatbeat.py` | 编排完整生命周期：初始化、信号注册、启动分析、`START` 事件记录，以及漂移校正的心跳循环。 |

## 环境要求

- Python 3.10 或更高版本。
- 具有 `/proc/sys/kernel/random/boot_id` 的 Linux 系统（所有现代内核均支持）。目标平台为 Arch Linux，但满足上述条件的任何 Linux 发行版均可使用。
- 运行时不需要任何第三方 Python 包。

## 安装

克隆仓库：

```bash
git clone https://github.com/<owner>/serverHeartbeat.git
cd serverHeartbeat
```

无需其他安装步骤，程序可直接运行。

## 配置

所有参数均可通过环境变量覆盖：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HEARTBEAT_LOG_DIR` | `./heartbeatLog` | 所有 JSONL 日志文件的存储目录。 |
| `HEARTBEAT_INTERVAL` | `60` | 心跳写入间隔（秒）。 |
| `TIME_JUMP_THRESHOLD` | `2.0` | 触发时间跳变标记的最小墙上时钟与单调时钟偏差（秒）。 |

示例：

```bash
HEARTBEAT_INTERVAL=30 HEARTBEAT_LOG_DIR=/var/log/serverHeartbeat python heatbeat.py
```

## 使用方法

直接运行：

```bash
python heatbeat.py
```

程序将依次执行：

1. 若日志目录不存在则创建。
2. 从 `/proc/sys/kernel/random/boot_id` 读取当前启动 ID。
3. 分析上一次运行（若存在事件历史），并写入 `ANALYSIS` 事件。
4. 向 `events.jsonl` 记录 `START` 事件。
5. 进入心跳循环，每隔指定间隔向当天的日志文件写入一条 `HEARTBEAT` 条目。
6. 收到 `SIGTERM` 或 `SIGINT` 时，记录 `SHUTDOWN` 事件并正常退出。

所有人类可读的状态信息均输出到 stderr，在 systemd 下运行时可通过 `journalctl` 查看。

## 日志格式

所有日志文件使用 JSON Lines 格式（每行一个 JSON 对象）。每条记录包含以下公共字段：

```json
{
    "event": "HEARTBEAT",
    "wallTime": "2026-03-29T12:00:00.123456+00:00",
    "monoNs": 987654321000000,
    "bootId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `event` | string | `START`、`HEARTBEAT`、`SHUTDOWN` 或 `ANALYSIS` 之一。 |
| `wallTime` | string | ISO-8601 格式的 UTC 墙上时钟时间。 |
| `monoNs` | integer | `CLOCK_MONOTONIC` 的纳秒值。仅在同一次启动（同一 `bootId`）内可比较。 |
| `bootId` | string | `/proc/sys/kernel/random/boot_id` 的内容，每次重启后改变。 |

`SHUTDOWN` 事件包含额外的 `signal` 字段（如 `"SIGTERM"`）。`ANALYSIS` 事件包含嵌套的 `analysis` 对象，内含完整的分析报告。

## 启动分析

每次服务启动时，将对上一个启动周期执行以下分析：

1. **定位上一个 `START` 事件**——在 `events.jsonl` 中逆序查找，并提取其 `bootId`。
2. **收集该 `bootId` 的所有心跳**——从每日日志文件中筛选。
3. **计算运行时间**——`(lastHeartbeat.monoNs - start.monoNs) / 1e9` 秒。
4. **估算关机时间窗口**——从最后一次心跳的墙上时间到该时间加上一个心跳间隔。
5. **判定关机类型**——若存在具有相同 `bootId` 的 `SHUTDOWN` 事件，则为正常关机；否则标记为异常关机（断电、内核崩溃、OOM 终止等）。
6. **检测时间跳变**——对每对相邻心跳，比较 `wallTime` 增量与 `monoNs` 增量。若差值超过 `TIME_JUMP_THRESHOLD` 秒，则记录一次时间跳变。

分析结果以 `ANALYSIS` 事件持久化到 `events.jsonl`，同时以人类可读格式输出到 stderr。

## systemd 集成

创建服务单元文件（如 `/etc/systemd/system/serverHeartbeat.service`）：

```ini
[Unit]
Description=Server Heartbeat Logger
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python /path/to/serverHeartbeat/heatbeat.py
Environment=HEARTBEAT_LOG_DIR=/var/log/serverHeartbeat
Environment=HEARTBEAT_INTERVAL=60
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl enable --now serverHeartbeat.service
```

查看日志：

```bash
journalctl -u serverHeartbeat.service -f
```

## 开发

### 环境搭建

```bash
python -m venv .venv
source .venv/bin/activate
pip install ruff mypy pytest
```

### 代码检查与类型校验

```bash
ruff format .
ruff check --fix .
mypy heartbeatConfig.py heartbeatIO.py heartbeatAnalyzer.py heatbeat.py --strict
```

### 测试

```bash
pytest                                          # 运行全部测试
pytest tests/test_heartbeatIO.py                # 运行单个测试文件
pytest tests/test_heartbeatIO.py::testSafeAppend  # 运行单个测试函数
pytest -s -v                                    # 详细输出
```

编写测试时，务必对 `/proc/` 读取和文件 I/O 进行 mock，避免对宿主系统状态产生依赖。请使用 `unittest.mock.patch` 或 pytest 的 `monkeypatch` fixture。

## 许可证

本项目基于 GNU General Public License v3.0 授权。详见 [LICENSE](LICENSE) 文件。

# serverHeartbeat

**Language: [English](README.md) | [Chinese (中文)](README_zh.md)**

A high-reliability heartbeat logger for Arch Linux servers. It periodically records UTC wall-clock time, monotonic time, and the Linux boot ID to structured JSON Lines (JSONL) files, enabling accurate uptime tracking, abnormal shutdown detection, and system time jump monitoring.

## Table of Contents

- [Motivation](#motivation)
- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Log Format](#log-format)
- [Startup Analysis](#startup-analysis)
- [systemd Integration](#systemd-integration)
- [Development](#development)
- [License](#license)

## Motivation

Standard system logging facilities (systemd journal, syslog) can lose records during unexpected power failures. This tool addresses that gap by maintaining its own append-only, fsync-backed log files that are flushed to stable storage after every write. By combining wall-clock timestamps with monotonic clock readings and the kernel boot ID, it provides a reliable timeline of server availability that survives clock adjustments, NTP steps, and unclean shutdowns.

## Features

- **Periodic heartbeat recording** at a configurable interval (default: 60 seconds).
- **Structured JSONL output** -- one JSON object per line, trivially parseable by standard tools.
- **fsync durability** -- every write is followed by `os.fsync()` on the same file descriptor, ensuring data reaches stable storage before the program proceeds.
- **Abnormal shutdown detection** -- on startup, the analyzer checks whether the previous run recorded a `SHUTDOWN` event. Its absence indicates a power loss, kernel panic, or other unclean termination.
- **Uptime calculation via monotonic clock** -- `time.monotonic_ns()` is immune to wall-clock adjustments, providing accurate uptime figures even when NTP steps the system clock.
- **System time jump detection** -- consecutive heartbeats are compared for discrepancies between wall-clock deltas and monotonic deltas. Jumps exceeding a configurable threshold are flagged.
- **Graceful shutdown handling** -- `SIGTERM` and `SIGINT` are caught to record a `SHUTDOWN` event before the process exits, allowing clean differentiation from abnormal terminations.
- **Daily log rotation** -- heartbeat entries are written to date-stamped files (`heartbeat_YYYY-MM-DD.jsonl`), one file per UTC day.
- **Zero runtime dependencies** -- the entire application uses only the Python standard library.

## Architecture

```
serverHeartbeat/
├── heatbeat.py            # Main entry point: signal handling, startup analysis, heartbeat loop
├── heartbeatConfig.py     # Constants, environment variable overrides, system helpers
├── heartbeatIO.py         # fsync-backed JSONL write, robust JSONL read, file discovery
├── heartbeatAnalyzer.py   # Previous-run analysis: uptime, shutdown type, time jump detection
└── heartbeatLog/          # Created at runtime
    ├── events.jsonl           # Lifecycle events: START, SHUTDOWN, ANALYSIS
    └── heartbeat_YYYY-MM-DD.jsonl  # Daily heartbeat records
```

| Module | Responsibility |
|---|---|
| `heartbeatConfig.py` | Centralises all tuneable constants (`LOG_DIR`, `HEARTBEAT_INTERVAL`, `TIME_JUMP_THRESHOLD`) and provides low-level helpers for reading the boot ID, generating ISO-8601 timestamps, and querying `CLOCK_MONOTONIC`. |
| `heartbeatIO.py` | Provides `safeAppendJson()`, which opens a file with `O_APPEND`, writes a serialised JSON line, calls `os.fsync()` on the same fd, then closes it. Also provides a robust JSONL reader that skips corrupted lines without crashing. |
| `heartbeatAnalyzer.py` | On each startup, locates the previous `START` event, collects all heartbeats sharing the same `bootId`, computes uptime from monotonic timestamps, estimates the shutdown window, and scans for wall-time jumps. |
| `heatbeat.py` | Orchestrates the full lifecycle: initialisation, signal registration, startup analysis, `START` event recording, and the drift-corrected heartbeat loop. |

## Requirements

- Python 3.10 or later.
- A Linux system with `/proc/sys/kernel/random/boot_id` (standard on all modern kernels). The target platform is Arch Linux, though any Linux distribution meeting these criteria will work.
- No third-party Python packages are required at runtime.

## Installation

Clone the repository:

```bash
git clone https://github.com/<owner>/serverHeartbeat.git
cd serverHeartbeat
```

No further installation steps are needed. The program can be run directly.

## Configuration

All parameters can be overridden through environment variables:

| Variable | Default | Description |
|---|---|---|
| `HEARTBEAT_LOG_DIR` | `./heartbeatLog` | Directory for all JSONL log files. |
| `HEARTBEAT_INTERVAL` | `60` | Seconds between heartbeat writes. |
| `TIME_JUMP_THRESHOLD` | `2.0` | Minimum wall-vs-monotonic discrepancy (in seconds) to flag as a time jump. |

Example:

```bash
HEARTBEAT_INTERVAL=30 HEARTBEAT_LOG_DIR=/var/log/serverHeartbeat python heatbeat.py
```

## Usage

Run directly:

```bash
python heatbeat.py
```

The program will:

1. Create the log directory if it does not exist.
2. Read the current boot ID from `/proc/sys/kernel/random/boot_id`.
3. Analyse the previous run (if event history exists) and write an `ANALYSIS` event.
4. Record a `START` event to `events.jsonl`.
5. Enter the heartbeat loop, writing a `HEARTBEAT` entry to the current day's log file at each interval.
6. On `SIGTERM` or `SIGINT`, record a `SHUTDOWN` event and exit cleanly.

All human-readable status messages are emitted to stderr, making them visible in `journalctl` when running under systemd.

## Log Format

All log files use the JSON Lines format (one JSON object per line). Every entry contains the following common fields:

```json
{
    "event": "HEARTBEAT",
    "wallTime": "2026-03-29T12:00:00.123456+00:00",
    "monoNs": 987654321000000,
    "bootId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

| Field | Type | Description |
|---|---|---|
| `event` | string | One of `START`, `HEARTBEAT`, `SHUTDOWN`, or `ANALYSIS`. |
| `wallTime` | string | UTC wall-clock time in ISO-8601 format. |
| `monoNs` | integer | Value of `CLOCK_MONOTONIC` in nanoseconds. Only comparable within the same boot (same `bootId`). |
| `bootId` | string | Contents of `/proc/sys/kernel/random/boot_id`. Changes on every reboot. |

`SHUTDOWN` events include an additional `signal` field (e.g., `"SIGTERM"`). `ANALYSIS` events include a nested `analysis` object with the full report.

## Startup Analysis

Each time the service starts, it performs the following analysis on the previous boot cycle:

1. **Locate the last `START` event** in `events.jsonl` and extract its `bootId`.
2. **Collect all heartbeats** for that `bootId` from the daily log files.
3. **Compute uptime** as `(lastHeartbeat.monoNs - start.monoNs) / 1e9` seconds.
4. **Estimate the shutdown window**: between the last heartbeat's wall time and that time plus one heartbeat interval.
5. **Determine shutdown type**: if a `SHUTDOWN` event with the same `bootId` exists, the shutdown was normal; otherwise, it is flagged as abnormal (power loss, kernel panic, OOM kill, etc.).
6. **Detect time jumps**: for each pair of consecutive heartbeats, compare `wallTime` delta against `monoNs` delta. If they differ by more than `TIME_JUMP_THRESHOLD` seconds, a time jump is recorded.

The results are persisted as an `ANALYSIS` event in `events.jsonl` and printed in human-readable form to stderr.

## systemd Integration

Create a service unit file (e.g., `/etc/systemd/system/serverHeartbeat.service`):

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

Enable and start:

```bash
sudo systemctl enable --now serverHeartbeat.service
```

View logs:

```bash
journalctl -u serverHeartbeat.service -f
```

## Development

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install ruff mypy pytest
```

### Linting and Type Checking

```bash
ruff format .
ruff check --fix .
mypy heartbeatConfig.py heartbeatIO.py heartbeatAnalyzer.py heatbeat.py --strict
```

### Testing

```bash
pytest                                          # Run all tests
pytest tests/test_heartbeatIO.py                # Run a single test file
pytest tests/test_heartbeatIO.py::testSafeAppend  # Run a single test function
pytest -s -v                                    # Verbose output
```

When writing tests, always mock interactions with `/proc/` and file I/O to avoid host-system dependencies. Use `unittest.mock.patch` or `pytest`'s `monkeypatch` fixture.

## License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.

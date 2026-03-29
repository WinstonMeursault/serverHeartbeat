# AGENTS.md - Codebase Guide for AI Agents

## Overview
This repository contains `serverHeartbeat`, a Python-based high-reliability heartbeat logger designed specifically for Arch Linux servers. It continuously records UTC time, monotonic time, and the system boot ID to track uptime, detect abnormal shutdowns, and monitor potential system time jumps using structured JSONL logs.

## 1. Build, Lint, and Test Commands

Since this is a lightweight system utility written in Python, we rely on standard Python tooling for quality assurance.

### Environment Setup
We recommend using standard virtual environments for development:
```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies (only dev dependencies since the project is pure standard library)
pip install ruff mypy pytest
```

### Linting & Formatting
We strictly use `ruff` for both linting and formatting due to its speed and comprehensive rule set. We also use `mypy --strict` for static type checking.
- **Format code**:
  ```bash
  ruff format .
  ```
- **Lint code**:
  ```bash
  ruff check .
  ```
- **Fix lint issues automatically**:
  ```bash
  ruff check --fix .
  ```
- **Type checking** (Run strictly on all source files):
  ```bash
  mypy heartbeatConfig.py heartbeatIO.py heartbeatAnalyzer.py heatbeat.py --strict
  ```

### Testing
We use `pytest` for all unit and integration testing. Given the system-level nature of this tool, tests often require mocking system files.
- **Run all tests**:
  ```bash
  pytest
  ```
- **Run a single test file**:
  ```bash
  pytest tests/test_heartbeat.py
  ```
- **Run a specific test function**:
  ```bash
  pytest tests/test_heartbeat.py::test_boot_id_tracking
  ```
- **Run tests with verbose output (useful for debugging)**:
  ```bash
  pytest -s -v
  ```

## 2. Code Style Guidelines

### 2.1. Python Version & Standards
- The project targets Python 3.10+ (standard on modern Arch Linux systems).
- ZERO third-party dependencies are allowed for the core logic. Utilize only the standard library (e.g., `os`, `json`, `time`, `datetime`, `signal`).

### 2.2. Imports
- Group imports in the following strict order, separated by blank lines:
  1. Standard library imports (e.g., `os`, `sys`, `time`, `logging`).
  2. Local application/library specific imports.
- Always prefer absolute imports over relative imports.
- Let `ruff` handle the automatic sorting and grouping of imports.

### 2.3. Type Hinting
- All functions, methods, and classes MUST use strict type hinting compatible with `mypy --strict`.
- Use standard types from the `typing` module or built-in generic types.
```python
from typing import Optional, Any

def safeAppendJson(filePath: str, data: dict[str, Any]) -> bool:
    # implementation
    return True
```

### 2.4. Naming Conventions
- **Variables, Functions, and Methods**: `camelCase` (e.g., `safeAppendJson`, `getMonoNs`, `readBootId`). This is a key requirement for this repository.
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `HEARTBEAT_INTERVAL`, `LOG_DIR`).
- **Classes**: `PascalCase` (e.g., `HeartbeatLogger`).
- **Private Variables/Methods**: Prefix with a single underscore to denote internal use (e.g., `_findLastEventByType()`, `_currentBootId`).
- **File Names**: `camelCase` (e.g., `heartbeatAnalyzer.py`, `heartbeatIO.py`), although the main entry point is `heatbeat.py`.

### 2.5. Error Handling & Resilience
- Never use bare `except:` clauses. Catch specific exceptions (e.g., `FileNotFoundError`, `OSError`).
- The service must be highly resilient. Use exact control over file descriptors and `os.fsync()` for crucial writes to avoid data loss on power failure.
- Fail gracefully and skip malformed log lines (e.g., JSONDecodeError) rather than crashing.

### 2.6. Logging & Output
- Use the built-in `logging` module to output to stderr (`sys.stderr`), so systemd's journal captures it natively.
- For data persistence, use structured JSON Lines (JSONL) format instead of text logs, so parsing is robust. Do not use third-party libraries like `loguru`.

### 2.7. Architecture & Design Principles
- **Zero Dependencies**: Keep external dependencies to zero for the runtime. Rely on pure standard library.
- **Direct I/O Fsync**: When persisting events, use `os.open` + `os.write` + `os.fsync` on the exact same file descriptor to ensure the kernel flushes to hardware before proceeding.
- **Monotonic Clocks**: Rely on `time.monotonic_ns()` for uptime duration, rather than wall clocks which can jump (e.g., NTP syncing).
- **Single Responsibility**: Separate the logic for reading configs, OS interactions (`heartbeatIO.py`), analysis (`heartbeatAnalyzer.py`), and the main loop.

## 3. Cursor & Copilot Rules
- Always run `ruff format .` and `ruff check --fix .` before finalizing any code modification.
- Always verify types using `mypy --strict`.
- Never introduce any third-party pip dependencies (like `requests`, `loguru`) to the main application code.
- If making changes to how system time or boot IDs are fetched, ensure cross-reference with Arch Linux documentation to guarantee compatibility.
- When generating tests, always include `unittest.mock.patch` or `pytest.MonkeyPatch` for any `open()` calls to `/proc/` or `/var/` or file I/O to prevent unit tests from depending on the host system's exact state or altering host files.

---
*Note: This file is the definitive guide for AI agents operating within this repository. Adhere to these principles to maintain consistency, reliability, and security.*
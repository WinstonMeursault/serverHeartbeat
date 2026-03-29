"""Configuration constants and system-level helpers for serverHeartbeat.

All tuneable parameters are centralised here so that every other module
imports from a single source of truth.  Where sensible the value can be
overridden via an environment variable.
"""

import logging
import os
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
currentDir : str = os.path.dirname(os.path.realpath(__file__))
LOG_DIR: str = os.environ.get("HEARTBEAT_LOG_DIR", currentDir + "/heartbeatLog")
EVENTS_LOG: str = os.path.join(LOG_DIR, "events.jsonl")
BOOT_ID_PATH: str = "/proc/sys/kernel/random/boot_id"

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "60"))
TIME_JUMP_THRESHOLD: float = float(os.environ.get("TIME_JUMP_THRESHOLD", "2.0"))

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------
logger: logging.Logger = logging.getLogger("serverHeartbeat")


# ---------------------------------------------------------------------------
# System helpers
# ---------------------------------------------------------------------------
def readBootId() -> str:
    """Read the current Linux boot ID from procfs.

    Returns:
        The boot-id string (UUID without dashes trimmed), or ``"unknown"``
        when the file cannot be read.
    """
    try:
        with open(BOOT_ID_PATH, "r", encoding="ascii") as fh:
            return fh.read().strip()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.error("Failed to read boot_id from %s: %s", BOOT_ID_PATH, exc)
        return "unknown"


def getWallTimeIso() -> str:
    """Return the current UTC wall-clock time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def getMonoNs() -> int:
    """Return the current value of ``CLOCK_MONOTONIC`` in nanoseconds."""
    return time.monotonic_ns()


def dailyLogPath(dateStr: str) -> str:
    """Build the full path for a daily heartbeat JSONL file.

    Args:
        dateStr: Date in ``YYYY-MM-DD`` format.
    """
    return os.path.join(LOG_DIR, f"heartbeat_{dateStr}.jsonl")


def todayDateStr() -> str:
    """Return today's UTC date formatted as ``YYYY-MM-DD``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

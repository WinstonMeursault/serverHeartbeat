"""serverHeartbeat - high-reliability heartbeat logger for Arch Linux.

This is the main entry-point.  It:

1. Reads the current boot-id.
2. Analyses the previous run (uptime, shutdown type, time jumps).
3. Records a ``START`` event.
4. Enters a durable heartbeat loop (``HEARTBEAT`` + fsync every interval).
5. On ``SIGTERM`` / ``SIGINT`` records a ``SHUTDOWN`` event before exiting.
"""

import logging
import signal
import sys
import time
from types import FrameType
from typing import Any, Optional

from heartbeatAnalyzer import analyzeLastRun
from heartbeatConfig import (
    EVENTS_LOG,
    HEARTBEAT_INTERVAL,
    dailyLogPath,
    getMonoNs,
    getWallTimeIso,
    readBootId,
    todayDateStr,
)
from heartbeatIO import ensureLogDir, safeAppendJson

# ---------------------------------------------------------------------------
# Logging – stderr so systemd journal captures it automatically
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    stream=sys.stderr,
)
logger: logging.Logger = logging.getLogger("serverHeartbeat")

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_running: bool = True
_currentBootId: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _buildEntry(
    eventType: str,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Construct a structured log entry with common fields."""
    entry: dict[str, Any] = {
        "event": eventType,
        "wallTime": getWallTimeIso(),
        "monoNs": getMonoNs(),
        "bootId": _currentBootId,
    }
    if extra:
        entry.update(extra)
    return entry


def _formatUptime(totalSeconds: float) -> str:
    """Format a duration in seconds as ``Xh Ym Zs``."""
    total = int(totalSeconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours}h {minutes}m {seconds}s"


# ---------------------------------------------------------------------------
# Signal handling – write SHUTDOWN event, then exit
# ---------------------------------------------------------------------------
def _handleShutdownSignal(
    signum: int,
    _frame: Optional[FrameType],
) -> None:
    """Record a ``SHUTDOWN`` event and terminate cleanly."""
    global _running  # noqa: PLW0603
    _running = False
    sigName = signal.Signals(signum).name
    logger.info("Received %s – recording shutdown event", sigName)
    shutdownEntry = _buildEntry("SHUTDOWN", {"signal": sigName})
    safeAppendJson(EVENTS_LOG, shutdownEntry)
    logger.info("Shutdown complete")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Startup analysis – pretty-print results to journal
# ---------------------------------------------------------------------------
def _runStartupAnalysis() -> None:
    """Invoke the analyser and log a human-readable summary."""
    analysis = analyzeLastRun()
    if analysis is None:
        logger.info("No previous run data (first run or events log missing)")
        return

    # Persist the machine-readable analysis
    analysisEntry = _buildEntry("ANALYSIS", {"analysis": analysis})
    safeAppendJson(EVENTS_LOG, analysisEntry)

    # Human-readable summary for journalctl
    uptime = analysis.get("uptimeSeconds", 0.0)
    logger.info("=== Previous Run Analysis ===")
    logger.info("  Boot ID:        %s", analysis.get("prevBootId", "?")[:12])
    logger.info("  Last start:     %s", analysis.get("lastStartTime", "?"))
    logger.info(
        "  Last heartbeat: %s",
        analysis.get("lastHeartbeatTime") or "none",
    )
    logger.info("  Uptime:         %s (%.1f s)", _formatUptime(uptime), uptime)

    window = analysis.get("shutdownWindow")
    if window:
        logger.info("  Shutdown window: [%s ~ %s]", window[0], window[1])

    if analysis.get("abnormalShutdown"):
        logger.warning("  *** ABNORMAL SHUTDOWN DETECTED ***")
    else:
        logger.info("  Shutdown type:  normal (SIGTERM received)")

    timeJumps: list[dict[str, Any]] = analysis.get("timeJumps", [])
    if timeJumps:
        logger.warning("  Wall-time jumps: %d detected", len(timeJumps))
        for jump in timeJumps:
            logger.warning(
                "    wall=%.3fs  mono=%.3fs  jump=%.3fs",
                jump["wallDeltaSec"],
                jump["monoDeltaSec"],
                jump["jumpAmountSec"],
            )
    logger.info("=============================")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Entry-point: analyse, record START, then loop heartbeats."""
    global _currentBootId  # noqa: PLW0603

    ensureLogDir()
    _currentBootId = readBootId()
    logger.info(
        "serverHeartbeat starting  boot_id=%s  interval=%ds",
        _currentBootId[:12],
        HEARTBEAT_INTERVAL,
    )

    # Register graceful-shutdown handlers
    signal.signal(signal.SIGTERM, _handleShutdownSignal)
    signal.signal(signal.SIGINT, _handleShutdownSignal)

    # Analyse the previous boot cycle
    _runStartupAnalysis()

    # Record this boot's START event
    safeAppendJson(EVENTS_LOG, _buildEntry("START"))
    logger.info("START event recorded")

    # Heartbeat loop – drift-corrected via monotonic clock
    logger.info("Entering heartbeat loop")
    nextWake: float = time.monotonic() + HEARTBEAT_INTERVAL
    while _running:
        entry = _buildEntry("HEARTBEAT")
        logPath = dailyLogPath(todayDateStr())
        safeAppendJson(logPath, entry)
        logger.debug("Heartbeat written to %s", logPath)

        sleepDuration = nextWake - time.monotonic()
        if sleepDuration > 0:
            time.sleep(sleepDuration)
        nextWake += HEARTBEAT_INTERVAL


if __name__ == "__main__":
    main()

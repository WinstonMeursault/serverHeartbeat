"""Startup analysis for serverHeartbeat.

On every launch the service calls ``analyzeLastRun()`` which:

1. Locates the most recent ``START`` event in *events.jsonl*.
2. Collects all ``HEARTBEAT`` entries that share the same ``bootId``.
3. Computes uptime via monotonic time (immune to wall-clock changes).
4. Estimates a shutdown window (last heartbeat .. last heartbeat + interval).
5. Determines whether the previous shutdown was normal (``SHUTDOWN`` event
   present) or abnormal (missing – implies power loss / kernel panic).
6. Scans for wall-time jumps by comparing consecutive Δwall vs Δmono.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from heartbeatConfig import (
    EVENTS_LOG,
    HEARTBEAT_INTERVAL,
    TIME_JUMP_THRESHOLD,
)
from heartbeatIO import findDailyLogFiles, readJsonlFile

logger: logging.Logger = logging.getLogger("serverHeartbeat")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _findLastEventByType(
    events: list[dict[str, Any]],
    eventType: str,
) -> Optional[dict[str, Any]]:
    """Walk *events* in reverse and return the first with matching type."""
    for entry in reversed(events):
        if entry.get("event") == eventType:
            return entry
    return None


def _collectHeartbeatsForBoot(
    bootId: str,
    startWallTime: str,
) -> list[dict[str, Any]]:
    """Gather every ``HEARTBEAT`` that belongs to *bootId*.

    Only daily files whose date is >= the START date are scanned, which
    avoids reading irrelevant history while still handling multi-day runs.

    Returns:
        Heartbeat entries sorted by ``monoNs`` ascending.
    """
    try:
        startDate = datetime.fromisoformat(startWallTime).date()
    except (ValueError, TypeError):
        logger.warning(
            "Cannot parse start wall-time '%s'; skipping heartbeat collection",
            startWallTime,
        )
        return []

    heartbeats: list[dict[str, Any]] = []
    for logFile in findDailyLogFiles():
        baseName = os.path.basename(logFile)
        try:
            dateStr = baseName.removeprefix("heartbeat_").removesuffix(".jsonl")
            fileDate = datetime.strptime(dateStr, "%Y-%m-%d").date()
        except ValueError:
            continue
        if fileDate < startDate:
            continue

        for entry in readJsonlFile(logFile):
            if entry.get("event") == "HEARTBEAT" and entry.get("bootId") == bootId:
                heartbeats.append(entry)

    heartbeats.sort(key=lambda e: e.get("monoNs", 0))
    return heartbeats


def _detectTimeJumps(
    heartbeats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare consecutive heartbeats and flag wall-time vs mono-time drift.

    A "jump" means NTP stepped the clock, or someone ran ``date -s``, or
    the RTC was wrong at boot.

    Returns:
        A list of dicts, each describing one detected jump.
    """
    jumps: list[dict[str, Any]] = []
    for idx in range(1, len(heartbeats)):
        prev = heartbeats[idx - 1]
        curr = heartbeats[idx]
        try:
            prevWall = datetime.fromisoformat(prev["wallTime"])
            currWall = datetime.fromisoformat(curr["wallTime"])
            wallDelta = (currWall - prevWall).total_seconds()
            monoDelta = (curr["monoNs"] - prev["monoNs"]) / 1e9
            jumpAmount = wallDelta - monoDelta
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping time-jump check at index %d: %s", idx, exc)
            continue

        if abs(jumpAmount) > TIME_JUMP_THRESHOLD:
            jumps.append(
                {
                    "fromTime": prev["wallTime"],
                    "toTime": curr["wallTime"],
                    "wallDeltaSec": round(wallDelta, 3),
                    "monoDeltaSec": round(monoDelta, 3),
                    "jumpAmountSec": round(jumpAmount, 3),
                }
            )
    return jumps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def analyzeLastRun() -> Optional[dict[str, Any]]:
    """Analyse the previous boot cycle and return a summary dict.

    The caller (``heatbeart.py``) is responsible for persisting the result
    as an ``ANALYSIS`` event and formatting it for the human-readable log.

    Returns:
        An analysis dict, or ``None`` when there is nothing to analyse
        (first ever run, or events log missing).
    """
    events = readJsonlFile(EVENTS_LOG)
    if not events:
        logger.info("No previous events – skipping analysis")
        return None

    lastStart = _findLastEventByType(events, "START")
    if lastStart is None:
        logger.info("No previous START event – skipping analysis")
        return None

    prevBootId: str = lastStart.get("bootId", "")
    startWallTime: str = lastStart.get("wallTime", "")
    startMonoNs: int = lastStart.get("monoNs", 0)

    # Was there a clean SHUTDOWN for that boot?
    lastShutdown = _findLastEventByType(events, "SHUTDOWN")
    normalShutdown: bool = (
        lastShutdown is not None and lastShutdown.get("bootId") == prevBootId
    )

    heartbeats = _collectHeartbeatsForBoot(prevBootId, startWallTime)

    # -- Edge case: START recorded but no heartbeats at all ----------------
    if not heartbeats:
        logger.info("No heartbeats for previous boot %s", prevBootId[:12])
        return {
            "prevBootId": prevBootId,
            "lastStartTime": startWallTime,
            "lastHeartbeatTime": None,
            "uptimeSeconds": 0.0,
            "shutdownWindow": None,
            "abnormalShutdown": not normalShutdown,
            "timeJumps": [],
            "note": "No heartbeat data for previous boot",
        }

    # -- Normal path -------------------------------------------------------
    lastHb = heartbeats[-1]
    lastHbWallTime: str = lastHb.get("wallTime", "")
    lastHbMonoNs: int = lastHb.get("monoNs", 0)

    uptimeSeconds = (lastHbMonoNs - startMonoNs) / 1e9

    # Estimate shutdown window
    try:
        lastHbDt = datetime.fromisoformat(lastHbWallTime)
        windowEnd = (lastHbDt + timedelta(seconds=HEARTBEAT_INTERVAL)).isoformat()
    except (ValueError, TypeError):
        windowEnd = "unknown"

    timeJumps = _detectTimeJumps(heartbeats)
    if timeJumps:
        logger.warning(
            "Previous boot %s had %d wall-time jump(s)",
            prevBootId[:12],
            len(timeJumps),
        )

    return {
        "prevBootId": prevBootId,
        "lastStartTime": startWallTime,
        "lastHeartbeatTime": lastHbWallTime,
        "uptimeSeconds": round(uptimeSeconds, 3),
        "shutdownWindow": [lastHbWallTime, windowEnd],
        "abnormalShutdown": not normalShutdown,
        "timeJumps": timeJumps,
    }

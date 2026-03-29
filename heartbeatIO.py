"""Safe, fsync-backed file I/O for serverHeartbeat.

Every public write function in this module guarantees that the data has
reached stable storage before returning, by calling ``os.fsync`` on the
**same** file-descriptor that was used for the write.  This avoids the
pitfall identified in code-review where re-opening a file just to fsync
a *different* fd has no durability guarantee.
"""

import json
import logging
import os
from typing import Any

from heartbeatConfig import LOG_DIR

logger: logging.Logger = logging.getLogger("serverHeartbeat")


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------
def ensureLogDir() -> None:
    """Create ``LOG_DIR`` (and parents) if it does not already exist."""
    os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Writing  (atomic append + fsync on the *same* fd)
# ---------------------------------------------------------------------------
def safeAppendJson(filePath: str, data: dict[str, Any]) -> bool:
    """Serialise *data* as a single JSON line and append it to *filePath*.

    The write uses ``O_APPEND`` so that concurrent writers (unlikely, but
    possible) produce well-formed interleaved lines rather than corruption.
    ``os.fsync`` is called on the **same fd** before closing to guarantee
    durability through a power loss.

    Args:
        filePath: Target JSONL file (created if absent).
        data:     Dictionary to serialise.

    Returns:
        ``True`` on success, ``False`` if the write failed.
    """
    fd: int = -1
    try:
        line: bytes = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(filePath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.write(fd, line)
        os.fsync(fd)
        return True
    except OSError as exc:
        logger.error("Failed to write to %s: %s", filePath, exc)
        return False
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Reading  (robust JSONL parser – skips corrupted lines)
# ---------------------------------------------------------------------------
def readJsonlFile(filePath: str) -> list[dict[str, Any]]:
    """Read every valid JSON object from a ``.jsonl`` file.

    Lines that are blank or contain malformed JSON are silently skipped
    (with a warning logged) so that a single corrupted line never
    prevents the rest of the file from being parsed.

    Args:
        filePath: Path to the JSONL file.

    Returns:
        A list of parsed dictionaries, in file order.
    """
    entries: list[dict[str, Any]] = []
    if not os.path.isfile(filePath):
        return entries
    try:
        with open(filePath, "r", encoding="utf-8") as fh:
            for lineNum, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    entries.append(json.loads(stripped))
                except json.JSONDecodeError:
                    logger.warning(
                        "Corrupted JSON at line %d in %s – skipped",
                        lineNum,
                        filePath,
                    )
    except OSError as exc:
        logger.error("Failed to read %s: %s", filePath, exc)
    return entries


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def findDailyLogFiles() -> list[str]:
    """Return all daily heartbeat log paths, sorted oldest-first.

    Lexicographic sort on the ``heartbeat_YYYY-MM-DD.jsonl`` filename is
    equivalent to chronological order.
    """
    if not os.path.isdir(LOG_DIR):
        return []
    files: list[str] = [
        os.path.join(LOG_DIR, name)
        for name in os.listdir(LOG_DIR)
        if name.startswith("heartbeat_") and name.endswith(".jsonl")
    ]
    files.sort()
    return files

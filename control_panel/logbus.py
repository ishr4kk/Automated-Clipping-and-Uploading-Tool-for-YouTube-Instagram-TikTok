"""Thread-safe logging bus shared by the whole control panel.

Every module (the main controller, the video generator and each uploader)
emits log entries into the bus. UI components subscribe and receive
entries from any thread; they are responsible for marshaling onto the
Tkinter main thread.

The bus also keeps a ring buffer of recent entries so the Master Console
can replay messages that arrived before the Console tab was opened.
"""

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .config import CONSOLE_RING_SIZE


LEVEL_INFO = "INFO"
LEVEL_OK = "OK"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"

LEVELS = (LEVEL_INFO, LEVEL_OK, LEVEL_WARN, LEVEL_ERROR)


@dataclass(frozen=True)
class LogEntry:
    source: str
    level: str
    message: str
    timestamp: datetime

    def format_time(self):
        return self.timestamp.strftime("%H:%M:%S")


class LogBus:
    """Publish/subscribe log bus.

    - ``subscribe(callback)`` registers a callback invoked with a LogEntry
      for every new entry (from any thread).
    - ``emit(source, level, message)`` is safe to call from worker threads.
    - ``ring`` is a deque of the most recent entries (replayable).
    """

    def __init__(self, ring_size=CONSOLE_RING_SIZE):
        self._listeners = []
        self._lock = threading.Lock()
        self.ring = deque(maxlen=ring_size)

    def subscribe(self, callback):
        """Register a listener. Returns an unsubscribe callable."""
        with self._lock:
            self._listeners.append(callback)
        return lambda: self.unsubscribe(callback)

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def emit(self, source, level, message, timestamp=None):
        entry = LogEntry(
            source=str(source),
            level=level if level in LEVELS else LEVEL_INFO,
            message=str(message),
            timestamp=timestamp or datetime.now(),
        )
        with self._lock:
            self.ring.append(entry)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:

                pass

    def snapshot(self):
        """Return the current ring buffer contents (newest last)."""
        with self._lock:
            return list(self.ring)

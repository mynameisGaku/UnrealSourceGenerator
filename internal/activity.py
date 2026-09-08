"""Bounded, thread-safe session history. No Tk calls and no file writes."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from .i18n import Message, msg


@dataclass(frozen=True)
class LogEntry:
    sequence: int
    timestamp: str
    level: str
    source: object
    message: object
    size: int


class ActivityLog:
    def __init__(self, max_entries: int = 5000, max_chars: int = 2_000_000):
        if max_entries < 1 or max_chars < 1:
            raise ValueError('Log limits must be positive.')
        self.max_entries, self.max_chars = max_entries, max_chars
        self._entries = deque()
        self._lock = Lock()
        self._sequence = self._revision = self._size = 0
        self.dropped = 0

    def add(self, message: object, level: str = 'info', source: object = 'App'):
        # Do not keep exceptions/tracebacks (and their entire stack frames) alive.
        if isinstance(message, BaseException):
            message = getattr(message, 'message', None) or str(message)
        rendered = str(message)
        if not rendered:
            return
        if len(rendered) > self.max_chars:
            message = rendered[-self.max_chars:]
            rendered = str(message)
        level = level if level in ('info', 'success', 'warning', 'error') else 'info'
        with self._lock:
            self._sequence += 1
            entry = LogEntry(self._sequence, datetime.now().strftime('%H:%M:%S'),
                             level, source, message, len(rendered))
            self._entries.append(entry)
            self._size += entry.size
            while len(self._entries) > self.max_entries or self._size > self.max_chars:
                self._size -= self._entries.popleft().size
                self.dropped += 1
            self._revision += 1

    def snapshot(self):
        with self._lock:
            return self._revision, tuple(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._size = self.dropped = 0
            self._revision += 1


LEVELS = {'info': msg('Info'), 'success': msg('Success'),
          'warning': msg('Warning'), 'error': msg('Error')}


def format_entry(entry: LogEntry, translator) -> str:
    prefix = f'{entry.timestamp} [{translator.render(LEVELS[entry.level])}] [{translator.render(entry.source)}] '
    text = translator.render(entry.message).replace('\r\n', '\n').replace('\r', '\n')
    # Raw process output is never interpreted as translation keys.
    text = text.replace('\x00', '')
    return prefix + text.rstrip('\n').replace('\n', '\n' + ' ' * len(prefix)) + '\n'

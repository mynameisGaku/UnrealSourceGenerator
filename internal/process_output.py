"""Stream a child process without blocking Tk or retaining unbounded output.

A reader drains the single merged pipe. The caller consumes bounded byte chunks,
handles timeout/cancellation and emits complete lines (including CR progress).
Only this module manages the child process; no GUI objects are touched here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import codecs
import locale
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Callable


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    seconds: float
    tail: str
    stopped: str = ''


def output_encodings() -> tuple[str, ...]:
    candidates = ['utf-8']
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            candidates.extend(f'cp{code}' for code in
                              (kernel.GetConsoleOutputCP(), kernel.GetOEMCP(), kernel.GetACP()) if code)
        except (AttributeError, OSError):
            pass
    candidates.append(locale.getpreferredencoding(False))
    return tuple(dict.fromkeys(candidates))


class OutputLines:
    """Decode per complete line: UTF-8 first, then the Windows output code page.

    Lines spanning reads keep their original bytes until a delimiter. Extremely
    long lines are split at a safe character boundary to bound pending storage.
    """
    LIMIT = 16384
    ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))')

    def __init__(self, emit: Callable[[str], None], encodings=None):
        self.emit = emit
        self.encodings = encodings or output_encodings()
        self.pending = bytearray()
        self.after_cr = False

    def _decode(self, raw: bytes, final=True):
        for encoding in self.encodings:
            try:
                decoder = codecs.getincrementaldecoder(encoding)(errors='strict')
                text = decoder.decode(raw, final=final)
                rest = decoder.getstate()[0]
                return text, rest
            except (UnicodeError, LookupError):
                continue
        return raw.decode(self.encodings[-1], errors='replace'), b''

    def _line(self, raw: bytes, final=True):
        text, rest = self._decode(raw, final)
        text = self.ANSI.sub('', text).replace('\x00', '').replace('\ufeff', '')
        # Terminal cursor control characters must not alter the log widget.
        text = ''.join(c for c in text if c >= ' ' or c == '\t')
        if text:
            self.emit(text)
        return rest

    def feed(self, chunk: bytes):
        if self.after_cr and chunk.startswith(b'\n'):
            chunk = chunk[1:]
        self.after_cr = False
        self.pending.extend(chunk)
        while self.pending:
            match = re.search(br'[\r\n]', self.pending)
            if match and match.start() <= self.LIMIT:
                index = match.start()
                cr = self.pending[index] == 13
                self._line(bytes(self.pending[:index]))
                del self.pending[:index + 1]
                if cr and self.pending.startswith(b'\n'):
                    del self.pending[:1]
                elif cr and not self.pending:
                    self.after_cr = True
            elif len(self.pending) > self.LIMIT:
                rest = self._line(bytes(self.pending[:self.LIMIT]), final=False)
                del self.pending[:self.LIMIT - len(rest)]
            else:
                break

    def finish(self):
        if self.pending:
            self._line(bytes(self.pending))
        self.pending.clear()


def _stop_process(process):
    """Terminate only this launched job, including normal batch descendants."""
    if sys.platform == 'win32':
        if process.poll() is None:
            try:
                taskkill = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/taskkill.exe')
                subprocess.run([taskkill, '/PID', str(process.pid), '/T', '/F'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.kill()
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def stream_process(command: list[str], cwd: Path, emit: Callable[[str], None], *,
                   timeout: float = 120, cancel: threading.Event | None = None,
                   encodings=None) -> ProcessResult:
    if timeout <= 0:
        raise ValueError('timeout must be positive')
    started = time.monotonic()
    cancel = cancel or threading.Event()
    if cancel.is_set():
        return ProcessResult(-1, 0, '', 'cancelled')
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                               start_new_session=sys.platform != 'win32')
    chunks = queue.Queue(maxsize=128)
    reader_stop = threading.Event()
    tail = deque(maxlen=80)
    def publish(value):
        while not reader_stop.is_set():
            try:
                chunks.put(value, timeout=.1)
                return
            except queue.Full:
                pass
    def read():
        try:
            while not reader_stop.is_set():
                chunk = process.stdout.read1(8192)
                if not chunk:
                    break
                publish(chunk)
        except (OSError, ValueError) as exc:
            publish(exc)
        finally:
            process.stdout.close()
            publish(None)
    def on_line(line):
        tail.append(line[-4096:])
        emit(line)
    lines = OutputLines(on_line, encodings)
    reader = threading.Thread(target=read, name='unrealsourcegen-output', daemon=True)
    reader.start()
    stopped, stop_at, eof = '', 0.0, False
    try:
        while not eof or process.poll() is None:
            now = time.monotonic()
            if not stopped and (cancel.is_set() or now - started >= timeout):
                stopped = 'cancelled' if cancel.is_set() else 'timeout'
                _stop_process(process)
                stop_at = time.monotonic()
            if stopped and time.monotonic() - stop_at > 3:
                # A custom detached child may retain an inherited pipe. Never
                # keep the GUI busy forever waiting on somebody else's handle.
                break
            if eof:
                time.sleep(.02)
                continue
            try:
                chunk = chunks.get(timeout=.05)
            except queue.Empty:
                continue
            if chunk is None:
                eof = True
            elif isinstance(chunk, BaseException):
                raise chunk
            else:
                lines.feed(chunk)
        lines.finish()
        returncode = process.wait(timeout=3)
        return ProcessResult(returncode, time.monotonic() - started, '\n'.join(tail)[-3500:], stopped)
    finally:
        reader_stop.set()
        if process.poll() is None or not eof:
            _stop_process(process)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        reader.join(timeout=.2)

"""Windowless process launcher used by gui.bat (not a CLI interface)."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    if sys.version_info < (3, 10):
        return 1
    try:
        import tkinter
    except ImportError:
        return 1
    root = Path(__file__).resolve().parent.parent
    exe = Path(sys.executable)
    if sys.platform == 'win32':
        candidate = exe.with_name('pythonw.exe')
        if candidate.is_file():
            exe = candidate
    try:
        subprocess.Popen([str(exe), str(root / 'gui.pyw')], cwd=root,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

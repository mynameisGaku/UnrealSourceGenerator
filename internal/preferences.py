"""Shared preference location for the GUI and startup-error reporting."""
from pathlib import Path
import json
import os
import sys


def settings_path() -> Path:
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', str(Path.home())))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    return base / 'CppSourceGenerator' / 'compact-ui.json'


def read_settings(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        allowed = {'language', 'project', 'target', 'template', 'folder', 'layout'}
        return {k: v for k, v in data.items() if k in allowed and isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}

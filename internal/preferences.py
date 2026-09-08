"""Shared preference location for the GUI and startup-error reporting."""
from pathlib import Path
import json
import os
import sys

from .identity import APP_NAME, LEGACY_APP_NAME


def settings_path() -> Path:
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', str(Path.home())))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    return base / APP_NAME / 'compact-ui.json'


def read_settings(path: Path) -> dict[str, str]:
    # Read legacy preferences only when the new default file does not exist.
    # Saving always uses the new path. Never overwrite/delete the old settings.
    # An explicit test/custom path does not inherit the user's preferences.
    if path == settings_path() and not path.exists():
        path = path.parent.parent / LEGACY_APP_NAME / path.name
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        allowed = {'language', 'project', 'target', 'template', 'folder', 'layout'}
        return {k: v for k, v in data.items() if k in allowed and isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}

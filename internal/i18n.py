"""Offline English/Japanese messages, independent of Tk and generation logic.

Only explicitly marked Message objects are translated. User input, paths, C++
identifiers and external process output are never used as translation keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import json
from typing import Any

DEFAULT_LANGUAGE = 'en'
LANGUAGES = {'en': 'English', 'ja': '日本語'}


def normalize_language(value: object) -> str:
    """No OS-locale detection: a new or invalid preference always means English."""
    return value if isinstance(value, str) and value in LANGUAGES else DEFAULT_LANGUAGE


@dataclass(frozen=True)
class Message:
    key: str
    values: tuple[tuple[str, Any], ...] = ()

    def __str__(self) -> str:
        # Logs and non-UI callers get deterministic English, not global state.
        return Translator().render(self)


def msg(key: str, **values: Any) -> Message:
    return Message(key, tuple(values.items()))


@lru_cache(maxsize=2)
def catalog(language: str) -> dict[str, str]:
    path = Path(__file__).with_name('locales') / f'{normalize_language(language)}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, UnicodeError, ValueError):
        # English message IDs remain usable even if a language file is missing.
        return {}


class Translator:
    def __init__(self, language: object = DEFAULT_LANGUAGE):
        self.language = normalize_language(language)

    def __call__(self, key: str | Message, **values: Any) -> str:
        return self.render(key if isinstance(key, Message) else msg(key, **values))

    def render(self, value: object) -> str:
        if isinstance(value, Message):
            source = catalog(self.language).get(value.key, catalog(DEFAULT_LANGUAGE).get(value.key, value.key))
            args = {k: self.render(v) for k, v in value.values}
            try:
                return source.format_map(args)
            except (KeyError, ValueError, IndexError):
                # A damaged translation must not make the GUI unusable.
                try:
                    return value.key.format_map(args)
                except (KeyError, ValueError, IndexError):
                    return value.key
        if isinstance(value, BaseException) and isinstance(getattr(value, 'message', None), Message):
            return self.render(value.message)
        return str(value)

"""Double-click to launch the application. No console interface."""
from pathlib import Path
import os
import sys
import traceback

sys.dont_write_bytecode = True


def fail(message):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'C++ Source Generator', 0x10)
    else:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror('C++ Source Generator', message, parent=root)
            root.destroy()
        except Exception:
            pass


def start():
    translations = None
    state_path = None
    try:
        if sys.version_info < (3, 10):
            raise RuntimeError('Python 3.10 or later is required.')
        from internal.i18n import Translator, msg
        from internal.preferences import read_settings, settings_path
        state_path = settings_path()
        translations = Translator(read_settings(state_path).get('language', 'en'))
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        from internal.ui import main
        main()
    except Exception as exc:
        directory = state_path.parent if state_path else Path(os.environ.get('APPDATA', str(Path.home()))) / 'CppSourceGenerator'
        log = directory / 'startup-error.log'
        suffix = ''
        try:
            directory.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc(), encoding='utf-8')
            suffix = translations(msg('\n\nDetails: {log}', log=log)) if translations else f'\n\nDetails: {log}'
        except OSError:
            pass
        if translations:
            text = translations(msg('Could not start the application.\n{error}{detail}', error=exc, detail=suffix))
        else:
            text = f'Could not start the application.\n{exc}{suffix}'
        fail(text)


if __name__ == '__main__':
    start()

"""Optional desktop actions; invoked only by the GUI."""
from pathlib import Path
import json
import os
import subprocess
import sys

from .model import Project, ValidationError
from .i18n import Message, msg
from .process_output import stream_process
import re


def open_folder(path: Path):
    while not path.is_dir() and path != path.parent:
        path = path.parent
    if sys.platform == 'win32':
        os.startfile(str(path))
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def project_command(project: Project) -> list[str]:
    if sys.platform != 'win32':
        raise ValidationError(msg('Project file updates must be run on Windows.'))
    association = str(json.loads(project.file.read_text(encoding='utf-8-sig')).get('EngineAssociation', ''))
    engine = None
    import winreg
    if association:
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r'Software\Epic Games\Unreal Engine\Builds', association),
            (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\EpicGames\Unreal Engine\{association}', 'InstalledDirectory'),
        ):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
                        candidate = Path(winreg.QueryValueEx(k, value)[0])
                    if (candidate / 'Engine').is_dir():
                        engine = candidate
                        break
                except OSError:
                    continue
            if engine:
                break
        if not engine:
            candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Epic Games' / f'UE_{association}'
            if (candidate / 'Engine').is_dir():
                engine = candidate
    else:
        for parent in project.root.parents:
            if (parent / 'Engine' / 'Build').is_dir():
                engine = parent
                break
    if engine:
        ubt = engine / 'Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.exe'
        if ubt.is_file():
            return [str(ubt), '-projectfiles', f'-project={project.file}', '-game', '-progress']
        build = engine / 'Engine/Build/BatchFiles/GenerateProjectFiles.bat'
        if build.is_file():
            line = subprocess.list2cmdline([str(build), f'-project={project.file}', '-game'])
            return [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c', f'"{line}"']
    local = project.root / 'GenerateProjectFiles.bat'
    if local.is_file():
        return [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c', f'""{local}""']
    raise ValidationError(msg('The Unreal Engine installation for this project was not found.'))


def update_project(project: Project, on_log=None, *, cancel=None, timeout=120) -> Message:
    def emit(message, level='info'):
        if on_log is not None:
            # Log delivery must not change the result of an engine operation.
            try:
                on_log(message, level)
            except Exception:
                pass

    command = project_command(project)
    emit(msg('Project: {path}', path=project.file))
    emit(msg('Command: {command}', command=subprocess.list2cmdline(command)))
    emit(msg('Working directory: {path}', path=project.root))
    def output(line):
        level = 'error' if re.search(r'(?i)\b(?:error|fatal|failed|failure)\b', line) else (
            'warning' if re.search(r'(?i)\bwarning\b', line) else 'info')
        emit(line, level)

    result = stream_process(command, project.root, output, timeout=timeout, cancel=cancel)
    emit(msg('Exit code: {code} ({seconds}s)', code=result.returncode, seconds=f'{result.seconds:.2f}'),
         'success' if not result.stopped and result.returncode == 0 else 'error')
    if result.stopped == 'timeout':
        raise ValidationError(msg('Project file update timed out after {seconds}s.\n{detail}',
                                  seconds=timeout, detail=result.tail))
    if result.stopped == 'cancelled':
        raise ValidationError(msg('Project file update was cancelled.\n{detail}', detail=result.tail))
    if result.returncode:
        raise ValidationError(msg('Project file update failed (exit code {code}).\n{detail}',
                                  code=result.returncode, detail=result.tail))
    return msg('Project files updated.')

"""Project discovery, write-free previews, guarded writes and undo.

There is deliberately no CLI parser or interactive console mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from typing import Iterable

from . import templates as tpl
from .i18n import Message, msg

ACTORS = frozenset(('Actor', 'Pawn', 'Character', 'PlayerController', 'GameModeBase',
                    'GameStateBase', 'PlayerState', 'HUD'))
COMPONENTS = frozenset(('ActorComponent', 'SceneComponent'))
SUBSYSTEMS = frozenset(tpl.KIND_GROUPS['Subsystem'])
PLAIN = frozenset(tpl.NS_PLAIN_TEMPLATES)
# Stable generation IDs; labels are translated only by the GUI.
LAYOUTS = {'Public / Private': 'split', 'Same Folder': 'flat',
           'Private Only': 'private', 'Public Only': 'public'}
LEGACY_LAYOUTS = {'同じフォルダ': 'flat', 'Private のみ': 'private', 'Public のみ': 'public'}


def resolve_layout(value: str) -> str:
    if value in LAYOUTS.values():
        return value
    return LAYOUTS.get(value, LEGACY_LAYOUTS.get(value, ''))

RESERVED = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
KEYWORDS = frozenset('alignas alignof and and_eq asm atomic_cancel atomic_commit '
                    'atomic_noexcept auto bitand bitor bool break case catch char char8_t '
                    'char16_t char32_t class compl concept const consteval constexpr constinit '
                    'const_cast continue co_await co_return co_yield decltype default delete '
                    'do double dynamic_cast else enum explicit export extern false float for '
                    'friend goto if inline int long mutable namespace new noexcept not not_eq '
                    'nullptr operator or or_eq private protected public reflexpr register '
                    'reinterpret_cast requires return short signed sizeof static static_assert '
                    'static_cast struct switch synchronized template this thread_local throw '
                    'true try typedef typeid typename union unsigned using virtual void volatile '
                    'wchar_t while xor xor_eq'.split())
SKIP_DIRS = {'Intermediate', 'Binaries', 'Saved', 'DerivedDataCache', 'Content', 'Resources',
             '__pycache__', '.git', '.vs', '.idea'}


class ValidationError(ValueError):
    def __init__(self, message: str | Message, field: str = ''):
        self.message = message
        super().__init__(str(message))
        self.field = field


@dataclass(frozen=True)
class Target:
    name: str
    folder: Path
    descriptor: Path
    kind: str = 'Runtime'
    plugin: str = ''

    @property
    def label(self) -> str:
        return f'{self.plugin} / {self.name}' if self.plugin else self.name

    @property
    def default_layout(self) -> str:
        return 'split' if any((self.folder / n).is_dir() for n in ('Public', 'Private')) else 'flat'

    @property
    def key(self) -> str:
        return str(self.folder)


@dataclass(frozen=True)
class Project:
    file: Path
    targets: tuple[Target, ...]

    @property
    def root(self) -> Path:
        return self.file.parent


def _walk(root: Path, suffix: str) -> Iterable[Path]:
    if not root.is_dir():
        return
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')
                         and not (Path(base) / d).is_symlink())
        for name in sorted(files):
            p = Path(base) / name
            if name.endswith(suffix) and not p.is_symlink():
                yield p


def read_json_snapshot(path: Path) -> tuple[dict, bytes]:
    """Parse and retain the same bytes used as the write-conflict snapshot."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode('utf-8-sig'))
    except (OSError, UnicodeError, ValueError) as e:
        raise ValidationError(msg('Could not read {file}.\n{error}', file=path.name, error=e), 'project') from e
    if not isinstance(data, dict):
        raise ValidationError(msg('The format of {file} is invalid.', file=path.name), 'project')
    return data, raw


def read_json(path: Path) -> dict:
    return read_json_snapshot(path)[0]


def _module_types(data: dict) -> dict[str, str]:
    entries = data.get('Modules', [])
    if not isinstance(entries, list) or any(not isinstance(m, dict) for m in entries):
        raise ValidationError(msg('The project or plugin Modules section is invalid.'), 'project')
    return {m['Name']: m.get('Type', 'Runtime') for m in entries
            if isinstance(m.get('Name'), str)}


def load_project(path: str | Path) -> Project:
    p = Path(path).expanduser().resolve()
    if p.is_dir():
        candidates = sorted(p.glob('*.uproject'))
        if len(candidates) != 1:
            raise ValidationError(msg('Please select a .uproject file.'), 'project')
        p = candidates[0]
    if p.suffix.lower() != '.uproject' or not p.is_file():
        raise ValidationError(msg('Please select a .uproject file.'), 'project')
    data = read_json(p)
    kinds = _module_types(data)
    targets = []
    for build in _walk(p.parent / 'Source', '.Build.cs'):
        name = build.name[:-9]
        targets.append(Target(name, build.parent, p, kinds.get(name, 'Runtime')))
    for plugin in _walk(p.parent / 'Plugins', '.uplugin'):
        plugin_data = read_json(plugin)
        kinds = _module_types(plugin_data)
        rel = plugin.parent.relative_to(p.parent / 'Plugins').as_posix()
        for build in _walk(plugin.parent / 'Source', '.Build.cs'):
            name = build.name[:-9]
            targets.append(Target(name, build.parent, plugin, kinds.get(name, 'Runtime'), rel))
    targets.sort(key=lambda t: (bool(t.plugin), t.kind != 'Runtime', t.label.casefold()))
    return Project(p, tuple(targets))


def find_project(*starts: Path) -> Path | None:
    """Nearest unambiguous ancestor, never an unrelated fallback project."""
    for start in starts:
        start = start.resolve()
        if start.is_file():
            start = start.parent
        for p in (start, *start.parents):
            candidates = sorted(p.glob('*.uproject'))
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                break
    return None


def required_prefix(template: str) -> str:
    if template in ('Enum', 'PlainEnum'):
        return 'E'
    if template in ('Struct', 'PlainStruct'):
        return 'F'
    if template == 'Interface':
        return 'I'
    if template == 'PlainClass':
        return ''
    return (tpl.TEMPLATES.get(template, {}).get('parent') or '')[:1]


def identifier(value: str, label: str | Message, field: str) -> str:
    n = value.strip()
    if not n:
        raise ValidationError(msg('Please enter {label}.', label=label), field)
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', n):
        raise ValidationError(msg('{label} must contain only letters, digits or underscores and cannot start with a digit.', label=label), field)
    if n in KEYWORDS or '__' in n or re.match(r'^_[A-Z]', n):
        raise ValidationError(msg('{name} is a reserved C++ name.', name=n), field)
    if n.upper() in RESERVED:
        raise ValidationError(msg('{name} is a reserved Windows name.', name=n), field)
    if len(n) > 180:
        raise ValidationError(msg('{label} is too long.', label=label), field)
    return n


def type_name(value: str, template: str) -> str:
    """Resolve the output name without ever modifying the user's input.

    Only the selected type's prefix is recognized (U is also accepted for an
    interface). Other leading letters belong to the name: FPSCounter must not
    lose its F when generating an Actor. A PascalCase/number/underscore boundary
    distinguishes an explicit prefix from words such as Animation or Enemy.
    """
    if template not in tpl.TEMPLATES:
        raise ValidationError(msg('Please select a type.'), 'template')
    n = identifier(value, msg('Name'), 'name')
    prefix = required_prefix(template)
    if not prefix:
        return n
    if n == prefix:
        raise ValidationError(msg('Please enter a name after the prefix.'), 'name')
    boundary = len(n) > 1 and (n[1].isupper() or n[1].isdigit() or n[1] == '_')
    if template == 'Interface' and n.startswith('U') and boundary:
        n = 'I' + n[1:]
    elif not (n.startswith(prefix) and boundary):
        n = prefix + n
    # Validate the final name as well: adding a prefix must not bypass limits.
    return identifier(n, msg('Name'), 'name')


def normalized_folder(value: str) -> str:
    value = value.strip().replace('\\', '/')
    if not value:
        return ''
    if value.startswith('/') or PureWindowsPath(value).drive:
        raise ValidationError(msg('Use a relative folder path within the module.'), 'folder')
    parts = []
    for part in value.split('/'):
        if part in ('', '.'):
            continue
        if part == '..' or part.endswith((' ', '.')) or re.search(r'[<>:"|?*\x00-\x1f]', part):
            raise ValidationError(msg('The folder name contains invalid characters.'), 'folder')
        if part.split('.')[0].upper() in RESERVED:
            raise ValidationError(msg('{name} is a reserved Windows name.', name=part), 'folder')
        parts.append(part)
    return '/'.join(parts)


def contained(path: Path, root: Path) -> Path:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as e:
        raise ValidationError(msg('The output path points outside the module.'), 'folder') from e
    # Reject links even inside the tree so replacing a link cannot affect the wrong file.
    p = path
    while p != root.parent:
        if p.is_symlink():
            raise ValidationError(msg('Symbolic links are not allowed in the output path.'), 'folder')
        if p == p.parent:
            break
        p = p.parent
    return path


def existing_folders(target: Target, layout: str | None = None) -> tuple[str, ...]:
    result = {''}
    layout = layout or target.default_layout
    sides = {'split': ('Public', 'Private'), 'private': ('Private',), 'public': ('Public',), 'flat': ('',)}
    roots = [target.folder / side for side in sides.get(layout, ('',))]
    for root in roots:
        if not root.is_dir():
            continue
        for base, dirs, _ in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')
                             and not (Path(base) / d).is_symlink())
            if layout == 'flat' and Path(base) == target.folder:
                dirs[:] = [d for d in dirs if d not in ('Public', 'Private')]
            rel = Path(base).relative_to(root).as_posix()
            if rel != '.':
                result.add(rel)
    return tuple(sorted(result, key=lambda s: (s.count('/'), s.casefold())))


def default_options(template: str) -> dict:
    return dict(with_api=True, blueprint_type=False, with_constructor=True,
                with_beginplay=True, with_tick=False, with_initialize=True,
                with_deinitialize=True, with_tickable=False, header_only=False,
                with_enum_conversion=False, with_struct_equality=False,
                with_struct_tostring=False, with_struct_netserialize=False,
                with_struct_datatable=False, with_struct_hash=False,
                namespace='', extra_includes='', append_to='')


@dataclass(frozen=True)
class Request:
    target: Target
    template: str
    name: str
    folder: str = ''
    layout: str = 'split'
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    path: Path
    content: str
    before: bytes | None
    role: str

    @property
    def after(self) -> bytes:
        # Preserve the existing file's newline convention and BOM on updates.
        text = self.content.replace('\r\n', '\n')
        if self.before and b'\r\n' in self.before:
            text = text.replace('\n', '\r\n')
        raw = text.encode('utf-8')
        if self.before and self.before.startswith(b'\xef\xbb\xbf'):
            raw = b'\xef\xbb\xbf' + raw
        return raw


@dataclass(frozen=True)
class Plan:
    root: Path
    name: str
    changes: tuple[Change, ...]
    appended: bool = False
    directories: tuple[Path, ...] = ()

    @property
    def modified(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.before is not None)


def _read_bytes(path: Path) -> bytes | None:
    if path.is_dir():
        raise ValidationError(msg('A folder with this name already exists: {name}', name=path.name))
    return path.read_bytes() if path.exists() else None


def _text(raw: bytes) -> str:
    try:
        return raw.decode('utf-8-sig').replace('\r\n', '\n')
    except UnicodeError as e:
        raise ValidationError(msg('The existing file is not UTF-8 and cannot be edited safely.')) from e


def _without_comments(text: str) -> str:
    """Mask comments but preserve character offsets and quoted literals."""
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda m: re.sub(r'[^\n]', ' ', m[0]) if m[0].startswith(('/',)) else m[0], text)


def _extra_includes(value: str) -> list[str]:
    lines = []
    for raw in re.split(r'[,\n]', value.strip()):
        raw = raw.strip()
        if not raw:
            continue
        raw = re.sub(r'^#\s*include\s*', '', raw)
        if raw.startswith('<') and raw.endswith('>'):
            inner, style = raw[1:-1], '<{}>'
        else:
            inner, style = raw.strip('"'), '"{}"'
        if not inner or re.search(r'[<>"\x00-\x1f]', inner):
            raise ValidationError(msg('The extra include syntax is invalid.'), 'options')
        lines.append('#include ' + style.format(inner))
    return list(dict.fromkeys(lines))


def _insert_includes(header: str, lines: list[str], generated: str = '') -> str:
    present = set(re.findall(r'^\s*(#include[^\n]+)', header, re.M))
    missing = [s for s in lines if s not in present and '.generated.h' not in s]
    gen_match = re.search(r'^\s*#include\s+"[^"\n]+\.generated\.h"[^\n]*$', header, re.M)
    if gen_match:
        i = gen_match.start()
        return header[:i] + ''.join(s + '\n' for s in missing) + header[i:]
    includes = list(re.finditer(r'^\s*#include[^\n]*\n', header, re.M))
    pragma = re.search(r'^#pragma once[^\n]*\n', header, re.M)
    guard = re.search(r'^#define\s+[A-Za-z_]\w*\s*\n', header, re.M)
    pos = includes[-1].end() if includes else pragma.end() if pragma else guard.end() if guard else 0
    addition = ''.join(s + '\n' for s in missing)
    if generated:
        addition += f'#include "{generated}.generated.h"\n'
    return header[:pos] + addition + header[pos:]


def _append_declaration(existing: str, snippet: str) -> str:
    # Recognize a conventional outer #ifndef/#define guard; never append beyond it.
    clean = _without_comments(existing).strip()
    guard = re.match(r'#ifndef\s+(\w+)\s*\n\s*#define\s+\1\b', clean)
    if guard:
        closing = list(re.finditer(r'^\s*#endif[^\n]*', existing, re.M))
        if not closing or _without_comments(existing[closing[-1].end():]).strip():
            raise ValidationError(msg('The include guard in the target header could not be identified.'), 'options')
        pos = closing[-1].start()
        return existing[:pos].rstrip() + '\n\n' + snippet.strip() + '\n\n' + existing[pos:]
    return existing.rstrip() + '\n\n' + snippet.strip() + '\n'


def _dependency(text: str, module: str, dependency: str, public: bool) -> str:
    clean = _without_comments(text)
    list_name = 'PublicDependencyModuleNames' if public else 'PrivateDependencyModuleNames'
    lists = ('PublicDependencyModuleNames',) if public else ('PublicDependencyModuleNames', 'PrivateDependencyModuleNames')
    for name in lists:
        for match in re.finditer(r'\b' + name + r'\s*\.\s*Add(?:Range)?\s*\([\s\S]*?\)\s*;', clean):
            if f'"{dependency}"' in match[0]:
                return text
    constructor = re.search(r'\b' + re.escape(module) + r'\s*\(\s*ReadOnlyTargetRules\s+\w+\s*\)\s*:\s*base\s*\([^)]*\)\s*\{', clean)
    if not constructor:
        raise ValidationError(msg('Add the {dependency} dependency to {module}.Build.cs.', module=module, dependency=dependency), 'target')
    i = constructor.end()
    return text[:i] + f'\n        {list_name}.Add("{dependency}");' + text[i:]


def output_dirs(req: Request) -> tuple[Path, Path]:
    sub = normalized_folder(req.folder)
    if req.layout not in LAYOUTS.values():
        raise ValidationError(msg('Please select a layout.'), 'layout')
    hside, cside = {'split': ('Public', 'Private'), 'flat': ('', ''),
                    'private': ('Private', 'Private'), 'public': ('Public', 'Public')}[req.layout]
    return (contained(req.target.folder / hside / sub, req.target.folder),
            contained(req.target.folder / cside / sub, req.target.folder))


def validate_target(project: Project, target: Target) -> None:
    if not project.file.is_file():
        raise ValidationError(msg('The project was not found. Please select it again.'), 'project')
    if target not in project.targets or not (target.folder / f'{target.name}.Build.cs').is_file():
        raise ValidationError(msg('Please select the module again.'), 'target')
    contained(target.folder, project.root)


def folder_plan(project: Project, target: Target, folder: str, layout: str) -> Plan:
    """Plan empty folders, never dummy source files or placeholder files."""
    validate_target(project, target)
    folder = normalized_folder(folder)
    if not folder:
        raise ValidationError(msg('Please enter a folder name.'), 'folder')
    req = Request(target, 'PlainClass', 'Folder', folder, layout)
    paths = tuple(dict.fromkeys(output_dirs(req)))
    _check_directories(paths, project.root)
    return Plan(project.root, folder, (), directories=paths)


def _check_directories(paths: Iterable[Path], root: Path) -> None:
    for path in paths:
        contained(path, root)
        # Check every parent before creating any side of a split folder.
        part = path
        while part != root:
            if part.exists() and not part.is_dir():
                raise ValidationError(msg('A file with this name already exists: {name}', name=part.name), 'folder')
            if part.parent.is_dir() and not part.exists():
                if any(p.name.casefold() == part.name.casefold() for p in part.parent.iterdir()):
                    raise ValidationError(msg('A name differing only in letter case already exists: {name}', name=part.name), 'folder')
            part = part.parent


def build_plan(project: Project, req: Request) -> Plan:
    validate_target(project, req.target)
    root = project.root
    name = type_name(req.name, req.template)
    opt = {**default_options(req.template), **req.options}
    ns = tpl.normalize_namespace(opt.get('namespace', ''))
    if ns and req.template not in PLAIN:
        raise ValidationError(msg('Namespaces are available only for plain C++ types.'), 'options')
    for segment in ns.split('::') if ns else []:
        identifier(segment, msg('Namespace'), 'options')
    opt['namespace'] = ns
    if opt.get('with_struct_hash'):
        opt['with_struct_equality'] = True
    if opt.get('header_only') and req.template not in PLAIN and not tpl.TEMPLATES[req.template]['header_only']:
        raise ValidationError(msg('Header-only generation is not supported for this type.'), 'options')
    if req.template == 'EditorSubsystem' and not req.target.kind.startswith('Editor'):
        raise ValidationError(msg('Select an Editor module for EditorSubsystem.'), 'target')
    if req.template in ACTORS | COMPONENTS and opt.get('with_tick'):
        opt['with_constructor'] = True
    header_only = tpl.TEMPLATES[req.template]['header_only'] or bool(opt.get('header_only'))
    hdir, cdir = output_dirs(req)
    append = str(opt.get('append_to') or '').strip()
    if append:
        if Path(append).name != append or '\\' in append or not append.endswith('.h'):
            raise ValidationError(msg('Select a .h file in the same folder as the append target.'), 'options')
        identifier(append[:-2], msg('Append Target'), 'options')
    header = contained(hdir / (append or f'{name}.h'), req.target.folder)
    cpp = contained(cdir / f'{header.stem}.cpp', req.target.folder)
    old_h, old_c = _read_bytes(header), _read_bytes(cpp)
    if append and old_h is None:
        raise ValidationError(msg('The target header for appending was not found.'), 'options')
    # Same filename elsewhere in the same module is almost always a layout mistake.
    # Do not silently delete or relocate someone else's implementation.
    if not append:
        for p in _walk(req.target.folder, '.h'):
            if p.name.casefold() == header.name.casefold() and p != header:
                raise ValidationError(msg('A header with this name already exists: {path}', path=p.relative_to(root)), 'name')
        for p in _walk(req.target.folder, '.cpp'):
            if p.name.casefold() == cpp.name.casefold() and (p != cpp or header_only):
                raise ValidationError(msg('Cannot change the layout while the existing .cpp remains: {path}', path=p.relative_to(root)), 'layout')
    # Build the same exact code for preview and commit.
    extra = _extra_includes(str(opt.get('extra_includes') or ''))
    values = {**opt, 'class_name': name, 'template': req.template, 'extra_includes': ''}
    info = tpl.TEMPLATES[req.template]
    htext = tpl.build_header_content(values, info, req.target.name.upper() + '_API')
    htext = _insert_includes(htext, extra)
    inc = header.name if hdir == cdir else '/'.join(filter(None, (normalized_folder(req.folder), header.name)))
    ctext = '' if header_only else tpl.build_cpp_content(values, info, inc)
    if ns:
        htext, ctext = tpl._apply_namespace(htext, ctext, ns)
    if append:
        existing = _text(old_h)
        clean = _without_comments(existing)
        names = [name, 'U' + name[1:]] if req.template == 'Interface' else [name]
        for n in names:
            if re.search(r'\b(?:class|struct|enum)\s+(?:class\s+)?(?:\w+_API\s+)?' + re.escape(n) + r'\b', clean):
                raise ValidationError(msg('{name} is already defined in the target header.', name=n), 'name')
        gen_existing = re.findall(r'#include\s+"([^"\n]+)\.generated\.h"', clean)
        reflected = req.template not in PLAIN
        if gen_existing and (len(gen_existing) != 1 or gen_existing[0] != header.stem):
            raise ValidationError(msg('The generated.h include in the target header does not match its file name.'), 'options')
        incs = re.findall(r'^#include[^\n]+', htext, re.M)
        existing = _insert_includes(existing, incs, header.stem if reflected and not gen_existing else '')
        snippet = re.sub(r'^\s*#(?:include[^\n]*|pragma once)\s*\n', '', htext, flags=re.M).strip()
        htext = _append_declaration(existing, snippet)
        if not header_only and old_c is not None:
            before_cpp = _text(old_c)
            if f'"{inc}"' not in _without_comments(before_cpp):
                before_cpp = f'#include "{inc}"\n' + before_cpp
            ctext = before_cpp.rstrip() + '\n\n' + ctext.split('\n', 1)[1].lstrip()
    changes = [Change(header, htext, old_h, 'header')]
    if not header_only:
        changes.append(Change(cpp, ctext, old_c, 'cpp'))
    if req.template == 'EditorSubsystem':
        build = req.target.folder / f'{req.target.name}.Build.cs'
        raw = build.read_bytes()
        updated = _dependency(_text(raw), req.target.name, 'EditorSubsystem', req.layout in ('split', 'public'))
        if updated != _text(raw):
            changes.append(Change(build, updated, raw, 'dependency'))
    return Plan(root, name, tuple(changes), bool(append))


@dataclass
class Receipt:
    plan: Plan
    backup: Path | None
    created_dirs: list[Path] = field(default_factory=list)


def _mkdir(path: Path, made: list[Path]) -> None:
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for p in reversed(missing):
        try:
            p.mkdir()
        except FileExistsError:
            if not p.is_dir() or p.is_symlink():
                raise
        else:
            made.append(p)


def _replace(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix='.cppgen-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _check_snapshot(plan: Plan) -> None:
    for change in plan.changes:
        contained(change.path, plan.root)
        if _read_bytes(change.path) != change.before:
            raise ValidationError(msg('{file} has changed. Please refresh the preview.', file=change.path.name))


def commit(plan: Plan, *, allow_existing: bool = False) -> Receipt:
    if not plan.changes and not plan.directories:
        raise ValidationError(msg('There are no files or folders to create.'))
    _check_snapshot(plan)
    _check_directories(plan.directories, plan.root)
    if plan.modified and not allow_existing:
        raise ValidationError(msg('Changes to existing files require confirmation.'))
    made: list[Path] = []
    backup = None
    if plan.modified:
        backup = plan.root / 'Saved' / 'CppSourceGenerator' / 'Backups' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        contained(backup, plan.root)
        backup.mkdir(parents=True)
        manifest = []
        for i, c in enumerate(plan.changes):
            if c.before is not None:
                (backup / f'{i}.bin').write_bytes(c.before)
            manifest.append({'path': c.path.relative_to(plan.root).as_posix(),
                             'original': f'{i}.bin' if c.before is not None else None,
                             'sha256_after': hashlib.sha256(c.after).hexdigest()})
        (backup / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    done = []
    try:
        for directory in plan.directories:
            _check_directories((directory,), plan.root)
            _mkdir(directory, made)
        for c in plan.changes:
            contained(c.path, plan.root)
            if _read_bytes(c.path) != c.before:
                raise ValidationError(msg('{file} changed during generation.', file=c.path.name))
            _mkdir(c.path.parent, made)
            if c.before is None:
                # Exclusive creation prevents accidentally replacing a newly-created file.
                with c.path.open('xb') as stream:
                    try:
                        stream.write(c.after)
                        stream.flush()
                        os.fsync(stream.fileno())
                    except Exception:
                        stream.close()
                        c.path.unlink(missing_ok=True)
                        raise
            else:
                _replace(c.path, c.after)
            done.append(c)
    except Exception as e:
        failed = []
        for c in reversed(done):
            try:
                if _read_bytes(c.path) != c.after:
                    failed.append(c.path.name)
                    continue
                if c.before is None:
                    c.path.unlink()
                else:
                    _replace(c.path, c.before)
            except OSError:
                failed.append(c.path.name)
        for d in reversed(made):
            try:
                d.rmdir()
            except OSError:
                pass
        detail = msg('\nFiles that could not be restored: {files}\nBackup: {backup}', files=", ".join(failed), backup=backup) if failed else ''
        raise ValidationError(msg('Writing was stopped.\n{error}{detail}', error=e, detail=detail)) from e
    return Receipt(plan, backup, made)


def undo(receipt: Receipt) -> None:
    if not receipt.plan.changes and receipt.plan.directories:
        _undo_folders(receipt)
        return
    # Check ALL files before changing ANY of them.
    for c in receipt.plan.changes:
        contained(c.path, receipt.plan.root)
        if _read_bytes(c.path) != c.after:
            raise ValidationError(msg('{file} was edited after generation. Nothing was undone.', file=c.path.name))
    undone = []
    try:
        for c in reversed(receipt.plan.changes):
            if c.before is None:
                c.path.unlink()
            else:
                _replace(c.path, c.before)
            undone.append(c)
    except OSError as e:
        failed = []
        for c in reversed(undone):
            try:
                _replace(c.path, c.after)
            except OSError:
                failed.append(c.path.name)
        detail = msg('\nRestore failed: {files}', files=', '.join(failed)) if failed else ''
        raise ValidationError(msg('Undo failed.{detail}\n{error}', detail=detail, error=e)) from e
    for p in reversed(receipt.created_dirs):
        try:
            p.rmdir()
        except OSError:
            pass


def _undo_folders(receipt: Receipt) -> None:
    """Only remove empty directories created by this operation; never recurse."""
    made = set(receipt.created_dirs)
    for directory in receipt.created_dirs:
        contained(directory, receipt.plan.root)
        if not directory.is_dir() or any(p not in made for p in directory.iterdir()):
            raise ValidationError(msg('The added folders have changed. Nothing was undone.'))
    removed = []
    try:
        for directory in reversed(receipt.created_dirs):
            contained(directory, receipt.plan.root)
            directory.rmdir()
            removed.append(directory)
    except (OSError, ValidationError) as e:
        failures = []
        for directory in reversed(removed):
            try:
                contained(directory, receipt.plan.root)
                directory.mkdir(exist_ok=True)
            except (OSError, ValidationError):
                failures.append(directory.name)
        detail = (msg('\nFolders that could not be restored: {folders}', folders=', '.join(failures))) if failures else ''
        raise ValidationError(msg('Could not undo folder creation.\n{error}{detail}', error=e, detail=detail)) from e


def available_plugins(project: Project) -> dict[str, Path]:
    """Include content-only plugins, even before they have their first module."""
    result = {}
    for descriptor in _walk(project.root / 'Plugins', '.uplugin'):
        contained(descriptor, project.root)
        label = descriptor.parent.relative_to(project.root / 'Plugins').as_posix()
        if label in result:
            label += ' / ' + descriptor.stem
        result[label] = descriptor
    return result


def scaffold_plan(project: Project, name: str, kind: str, *, plugin: bool = False,
                  split: bool = True, plugin_descriptor: Path | None = None) -> Plan:
    # Refresh before planning so newly added modules cannot be duplicated using
    # a stale GUI selection. All mutations still happen only in commit().
    project = load_project(project.file)
    name = identifier(name, msg('Name'), 'name')
    if name.startswith('_') or kind not in ('Runtime', 'Editor'):
        raise ValidationError(msg('Start the name with a letter and select Runtime or Editor.'))
    plugins = available_plugins(project)
    if plugin_descriptor and plugin_descriptor not in plugins.values():
        raise ValidationError(msg('Please select the plugin again.'))
    if plugin and any(d.stem.casefold() == name.casefold() for d in plugins.values()):
        raise ValidationError(msg('A plugin with this name already exists.'))
    # Descriptors can declare a module whose source files are not present yet.
    snapshots = {p: read_json_snapshot(p) for p in (project.file, *plugins.values())}
    for data, _ in snapshots.values():
        if any(n.casefold() == name.casefold() for n in _module_types(data)):
            raise ValidationError(msg('A module with this name is already registered.'))
    plugin_root = project.root / 'Plugins' / name
    base = plugin_root if plugin else plugin_descriptor.parent if plugin_descriptor else project.root
    module = contained(base / 'Source' / name, project.root)
    if module.exists() or any(t.name.casefold() == name.casefold() for t in project.targets):
        raise ValidationError(msg('A module with this name already exists.'))
    if plugin and plugin_root.exists():
        raise ValidationError(msg('A plugin folder with this name already exists.'))
    _check_directories((module,), project.root)
    hdir, cdir = (module / 'Public', module / 'Private') if split else (module, module)
    build = f'''using UnrealBuildTool;

public class {name} : ModuleRules
{{
    public {name}(ReadOnlyTargetRules Target) : base(Target)
    {{
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {{ "Core", "CoreUObject", "Engine" }});
    }}
}}
'''
    primary = not any(not t.plugin for t in project.targets) and not plugin and not plugin_descriptor
    if primary and kind != 'Runtime':
        raise ValidationError(msg('Please add a Runtime module first.'))
    macro = f'IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, {name}, "{name}");' if primary else f'IMPLEMENT_MODULE(FDefaultModuleImpl, {name});'
    changes = [Change(module / f'{name}.Build.cs', build, None, 'module'),
               Change(hdir / f'{name}.h', '#pragma once\n\n#include "CoreMinimal.h"\n', None, 'module'),
               Change(cdir / f'{name}.cpp', f'#include "{name}.h"\n#include "Modules/ModuleManager.h"\n\n{macro}\n', None, 'module')]
    def add_json(path: Path, data: dict, before: bytes | None):
        changes.append(Change(path, json.dumps(data, ensure_ascii=False, indent='\t') + '\n', before, 'descriptor'))
    entry = {'Name': name, 'Type': kind, 'LoadingPhase': 'Default'}
    if plugin:
        add_json(plugin_root / f'{name}.uplugin', {'FileVersion': 3, 'Version': 1,
                 'VersionName': '1.0', 'FriendlyName': name, 'Category': 'Other',
                 'CanContainContent': True, 'Modules': [entry]}, None)
        data, raw_descriptor = snapshots[project.file]
        entries = data.setdefault('Plugins', [])
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise ValidationError(msg('The Plugins section in the .uproject file is invalid.'))
        previous = next((e for e in entries if str(e.get('Name', '')).casefold() == name.casefold()), None)
        if previous is not None:
            previous.update(Name=name, Enabled=True)
        else:
            entries.append({'Name': name, 'Enabled': True})
        add_json(project.file, data, raw_descriptor)
    elif plugin_descriptor:
        data, raw_descriptor = snapshots[plugin_descriptor]
        data.setdefault('Modules', []).append(entry)
        add_json(plugin_descriptor, data, raw_descriptor)
    else:
        data, raw_descriptor = snapshots[project.file]
        if any(m.get('Name', '').casefold() == name.casefold() for m in data.get('Modules', [])):
            raise ValidationError(msg('A module with this name is already registered in the .uproject file.'))
        data.setdefault('Modules', []).append(entry)
        add_json(project.file, data, raw_descriptor)
        for target_file in sorted((project.root / 'Source').glob('*.Target.cs')):
            raw = target_file.read_bytes()
            text = _text(raw)
            clean = _without_comments(text)
            if kind == 'Editor' and not re.search(r'TargetType\s*\.\s*Editor', clean):
                continue
            if re.search(r'"' + re.escape(name) + r'"', clean):
                continue
            calls = list(re.finditer(r'\bExtraModuleNames\s*\.\s*Add(?:Range)?\s*\([\s\S]*?\)\s*;', clean))
            if not calls:
                raise ValidationError(msg('Could not locate the module registration in {file}. No changes were made.', file=target_file.name))
            pos = calls[-1].end()
            updated = text[:pos] + f'\n        ExtraModuleNames.Add("{name}");' + text[pos:]
            changes.append(Change(target_file, updated, raw, 'target'))
        # Blueprint-only project: create target rules rather than leaving an unbuildable module.
        if primary and not list((project.root / 'Source').glob('*.Target.cs')):
            project_name = identifier(project.file.stem, msg('Project Name'), 'project')
            for suffix, type_ in (('', 'Game'), ('Editor', 'Editor')):
                content = f'''using UnrealBuildTool;

public class {project_name}{suffix}Target : TargetRules
{{
    public {project_name}{suffix}Target(TargetInfo Target) : base(Target)
    {{
        Type = TargetType.{type_};
        ExtraModuleNames.Add("{name}");
    }}
}}
'''
                changes.append(Change(project.root / 'Source' / f'{project_name}{suffix}.Target.cs', content, None, 'target'))
    return Plan(project.root, name, tuple(changes))

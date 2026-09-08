"""Prefix-free filenames, preserved C++ identifiers, branding and ignore rules."""
from dataclasses import replace
from pathlib import Path
import ast
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from internal import model as m, templates, preferences
from internal.identity import APP_NAME, LEGACY_APP_NAME
from tests.common import fixture, snapshot


class FilenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Project 日本語'
        self.project = m.load_project(fixture(self.root))
        self.target = next(t for t in self.project.targets if t.name == 'Game')

    def req(self, **kw):
        return replace(m.Request(self.target, 'Actor', 'PlayerBase'), **kw)

    def test_actor_base_and_prefixed_input_produce_identical_plans(self):
        base = m.build_plan(self.project, self.req())
        full = m.build_plan(self.project, self.req(name='APlayerBase'))
        self.assertEqual(base, full)
        self.assertEqual('APlayerBase', base.name)
        h, c = base.changes
        self.assertEqual('PlayerBase.h', h.path.name)
        self.assertEqual('PlayerBase.cpp', c.path.name)
        self.assertIn('class GAME_API APlayerBase : public AActor', h.content)
        self.assertIn('APlayerBase();', h.content)
        self.assertIn('#include "PlayerBase.generated.h"', h.content)
        self.assertIn('#include "PlayerBase.h"', c.content)
        self.assertIn('APlayerBase::APlayerBase()', c.content)
        self.assertNotIn('APlayerBase.generated.h', h.content)
        self.assertNotIn('APlayerBase.h', c.content)

    def test_every_type_and_layout_uses_prefix_free_paths_and_consistent_includes(self):
        for kind, info in templates.TEMPLATES.items():
            target = next(t for t in self.project.targets if t.name == ('EditorTools' if kind == 'EditorSubsystem' else 'Game'))
            for layout in ('split', 'flat', 'private', 'public'):
                for name in ('PlayerBase', m.required_prefix(kind) + 'PlayerBase'):
                    with self.subTest(kind=kind, layout=layout, input=name):
                        req = self.req(target=target, template=kind, name=name, folder='Actors/Nested', layout=layout)
                        p = m.build_plan(self.project, req)
                        h = next(c for c in p.changes if c.role == 'header')
                        self.assertEqual('PlayerBase.h', h.path.name)
                        self.assertIn(m.required_prefix(kind) + 'PlayerBase', h.content)
                        if kind not in m.PLAIN:
                            includes = [s for s in h.content.splitlines() if s.startswith('#include')]
                            self.assertEqual('#include "PlayerBase.generated.h"', includes[-1])
                        else:
                            self.assertNotIn('.generated.h', h.content)
                        for c in p.changes:
                            if c.role == 'cpp':
                                self.assertEqual('PlayerBase.cpp', c.path.name)
                                expected = 'Actors/Nested/PlayerBase.h' if layout == 'split' else 'PlayerBase.h'
                                self.assertTrue(c.content.startswith(f'#include "{expected}"'))

    def test_word_initials_and_other_prefix_letters_are_not_removed(self):
        for kind, name, cls in (
            ('Actor', 'Animation', 'AAnimation'), ('Actor', 'FPSCounter', 'AFPSCounter'),
            ('UObject', 'User', 'UUser'), ('UObject', 'IOSManager', 'UIOSManager'),
            ('Struct', 'Fighter', 'FFighter'), ('Enum', 'Enemy', 'EEnemy'),
            ('Interface', 'Item', 'IItem'), ('Actor', 'UBad', 'AUBad'),
            ('Actor', 'lowercase', 'Alowercase')):
            with self.subTest(kind=kind, name=name):
                p = m.build_plan(self.project, self.req(template=kind, name=name))
                self.assertEqual(cls, p.name)
                self.assertEqual(name + '.h', p.changes[0].path.name)

    def test_only_one_prefix_removed(self):
        p = m.build_plan(self.project, self.req(name='AAPlayerBase'))
        self.assertEqual('AAPlayerBase', p.name)
        self.assertEqual('APlayerBase.h', p.changes[0].path.name)
        self.assertIn('"APlayerBase.generated.h"', p.changes[0].content)

    def test_interface_accepts_base_i_or_u_and_keeps_both_declarations(self):
        plans = [m.build_plan(self.project, self.req(template='Interface', name=n))
                 for n in ('Interactable', 'IInteractable', 'UInteractable')]
        self.assertEqual(plans[0], plans[1])
        self.assertEqual(plans[0], plans[2])
        h, = plans[0].changes
        self.assertEqual('Interactable.h', h.path.name)
        self.assertIn('class UInteractable : public UInterface', h.content)
        self.assertIn('class GAME_API IInteractable', h.content)
        self.assertIn('"Interactable.generated.h"', h.content)

    def test_plain_class_has_no_implicit_prefix_to_remove(self):
        for name in ('APlayerBase', 'FUtility', 'Utility', 'IService', 'EHelper'):
            for inline in (False, True):
                with self.subTest(name=name, inline=inline):
                    p = m.build_plan(self.project, self.req(template='PlainClass', name=name, options={'header_only': inline}))
                    self.assertEqual(name, p.name)
                    self.assertEqual(name + '.h', p.changes[0].path.name)
                    self.assertEqual(1 if inline else 2, len(p.changes))

    def test_numeric_and_underscore_stems_are_valid_filenames(self):
        for name, stem in (('A2D', '2D'), ('A_Test', '_Test'), ('APlayer_2', 'Player_2')):
            with self.subTest(name=name):
                p = m.build_plan(self.project, self.req(name=name))
                self.assertEqual(stem + '.h', p.changes[0].path.name)
                self.assertIn(f'"{stem}.generated.h"', p.changes[0].content)
                receipt = m.commit(p)
                self.assertEqual(p.changes[0].after, p.changes[0].path.read_bytes())
                m.undo(receipt)

    def test_append_accepts_numeric_and_underscore_filenames_emitted_by_generator(self):
        for name, stem in (('A2D', '2D'), ('A_Test', '_Test')):
            with self.subTest(name=name):
                original = m.commit(m.build_plan(self.project, self.req(name=name)))
                req = self.req(template='Struct', name='FExtraData', options={'append_to': stem + '.h'})
                plan = m.build_plan(self.project, req)
                self.assertIn(f'"{stem}.generated.h"', plan.changes[0].content)
                self.assertIn('struct GAME_API FExtraData', plan.changes[0].content)
                added = m.commit(plan, allow_existing=True)
                m.undo(added)
                m.undo(original)

    def test_append_filename_validation_rejects_paths_and_reserved_devices(self):
        before = snapshot(self.root)
        for name in ('../Foo.h', 'Foo/Bar.h', 'Foo\\Bar.h', 'CON.h', 'COM1.h', 'A' * 181 + '.h', '.h', 'Bad Name.h'):
            with self.subTest(name=name), self.assertRaises(m.ValidationError):
                m.build_plan(self.project, self.req(options={'append_to': name}))
        self.assertEqual(before, snapshot(self.root))

    def test_device_names_after_prefix_removal_are_rejected_without_writes(self):
        before = snapshot(self.root)
        for kind, value in (('Actor', 'ACON'), ('UObject', 'UNUL'), ('Struct', 'FCOM1'),
                            ('Enum', 'ELPT1'), ('Interface', 'IAUX'), ('Interface', 'UCON'),
                            ('PlainStruct', 'FPRN'), ('PlainEnum', 'ECOM9')):
            with self.subTest(kind=kind, value=value), self.assertRaises(m.ValidationError) as error:
                m.build_plan(self.project, self.req(template=kind, name=value))
            self.assertEqual('name', error.exception.field)
            self.assertIn('Windows', str(error.exception))
        self.assertEqual(before, snapshot(self.root))

    def test_preview_commit_undo_roundtrip_and_input_preservation(self):
        req = self.req(folder='Gameplay/Characters', options={'with_tick': True})
        before = snapshot(self.root)
        plan = m.build_plan(self.project, req)
        self.assertEqual(before, snapshot(self.root))
        receipt = m.commit(plan)
        for c in plan.changes:
            self.assertEqual(c.after, c.path.read_bytes())
            self.assertTrue(c.path.name.startswith('PlayerBase.'))
        self.assertEqual('PlayerBase', req.name)
        self.assertEqual({'with_tick': True}, req.options)
        m.undo(receipt)
        self.assertEqual(before, snapshot(self.root))

    def test_existing_unprefixed_file_requires_confirmation_and_has_new_backup_path(self):
        p = m.build_plan(self.project, self.req())
        m.commit(p)
        modified = m.build_plan(self.project, self.req(name='APlayerBase', options={'with_tick': True}))
        with self.assertRaises(m.ValidationError):
            m.commit(modified)
        r = m.commit(modified, allow_existing=True)
        self.assertEqual(self.root / 'Saved' / APP_NAME / 'Backups', r.backup.parent)
        self.assertIn('PlayerBase.h', (r.backup / 'manifest.json').read_text())
        m.undo(r)
        for original in p.changes:
            self.assertEqual(original.after, original.path.read_bytes())

    def test_unprefixed_case_collision_is_not_overwritten(self):
        h = self.target.folder / 'Public/playerbase.h'
        h.write_text('// user data\n')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(name='APlayerBase'))
        self.assertEqual(before, snapshot(self.root))

    def test_old_prefixed_header_stops_duplicate_generation_without_renaming(self):
        h = self.target.folder / 'Public/APlayerBase.h'
        h.write_text('#include "APlayerBase.generated.h"\nclass APlayerBase {};\n')
        before = snapshot(self.root)
        for name in ('PlayerBase', 'APlayerBase'):
            with self.subTest(name=name), self.assertRaises(m.ValidationError) as error:
                m.build_plan(self.project, self.req(name=name))
            self.assertIn('prefixed file', str(error.exception))
        self.assertEqual(before, snapshot(self.root))

    def test_old_prefixed_cpp_alone_also_stops_duplicate_generation(self):
        (self.target.folder / 'Private/APlayerBase.cpp').write_text('// preserve\n')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req())
        self.assertEqual(before, snapshot(self.root))

    def test_old_interface_files_with_either_prefix_are_protected(self):
        for old in ('IInteractable.h', 'UInteractable.h'):
            h = self.target.folder / 'Public' / old
            h.write_text('// preserve\n')
            try:
                with self.assertRaises(m.ValidationError):
                    m.build_plan(self.project, self.req(template='Interface', name='Interactable'))
            finally:
                h.unlink()

    def test_append_target_is_literal_even_when_it_has_a_prefix(self):
        # Existing source files are not renamed and keep their own generated.h.
        h = self.target.folder / 'Public/AShared.h'
        h.write_text('#pragma once\n#include "CoreMinimal.h"\n#include "AShared.generated.h"\n\nclass AExisting {};\n')
        req = self.req(options={'append_to': 'AShared.h'})
        p = m.build_plan(self.project, req)
        self.assertEqual('AShared.h', p.changes[0].path.name)
        self.assertEqual('AShared.cpp', p.changes[1].path.name)
        self.assertEqual(1, p.changes[0].content.count('.generated.h'))
        self.assertIn('"AShared.generated.h"', p.changes[0].content)
        self.assertTrue(p.changes[1].content.startswith('#include "AShared.h"'))
        r = m.commit(p, allow_existing=True)
        self.assertFalse((h.parent / 'PlayerBase.h').exists())
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, replace(req, name='APlayerBase'))
        m.undo(r)
        self.assertNotIn('APlayerBase', h.read_text())

    def test_append_new_unprefixed_header_retains_its_include(self):
        m.commit(m.build_plan(self.project, self.req()))
        p = m.build_plan(self.project, self.req(template='Struct', name='FPlayerData', options={'append_to': 'PlayerBase.h'}))
        self.assertIn('FPlayerData', p.changes[0].content)
        self.assertIn('"PlayerBase.generated.h"', p.changes[0].content)
        self.assertNotIn('PlayerData.generated.h', p.changes[0].content)
        self.assertEqual(1, len(p.changes))

    def test_extra_includes_are_not_rewritten(self):
        p = m.build_plan(self.project, self.req(options={'extra_includes': 'AOtherActor.h, FSharedData.h'}))
        self.assertIn('#include "AOtherActor.h"', p.changes[0].content)
        self.assertIn('#include "FSharedData.h"', p.changes[0].content)
        self.assertIn('#include "PlayerBase.generated.h"', p.changes[0].content)

    def test_plugin_source_uses_same_naming_rule(self):
        d = self.root / 'Plugins/Vendor/ContentPlugin'
        d.mkdir(parents=True)
        (d / 'ContentPlugin.uplugin').write_text('{"Modules":[{"Name":"Feature","Type":"Runtime"}]}')
        folder = d / 'Source/Feature'
        folder.mkdir(parents=True)
        (folder / 'Feature.Build.cs').write_text('')
        project = m.load_project(self.project.file)
        target = next(t for t in project.targets if t.name == 'Feature')
        p = m.build_plan(project, self.req(target=target, folder='Actors'))
        self.assertEqual(folder / 'Public/Actors/PlayerBase.h', p.changes[0].path)
        self.assertEqual(folder / 'Private/Actors/PlayerBase.cpp', p.changes[1].path)
        self.assertIn('class FEATURE_API APlayerBase', p.changes[0].content)
        m.commit(p)
        self.assertTrue(p.changes[0].path.is_file())


class ProjectIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'APPDATA': str(self.root), 'XDG_CONFIG_HOME': str(self.root)})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_default_settings_path_uses_new_name_on_windows_and_linux(self):
        for system in ('win32', 'linux'):
            with self.subTest(system=system), patch.object(preferences.sys, 'platform', system):
                self.assertEqual(self.root / APP_NAME / 'compact-ui.json', preferences.settings_path())

    def test_legacy_settings_are_read_without_modifying_them(self):
        old = self.root / LEGACY_APP_NAME / 'compact-ui.json'
        old.parent.mkdir()
        content = '{"language":"ja","project":"old/Demo.uproject","layout":"split"}'
        old.write_text(content)
        new = preferences.settings_path()
        self.assertEqual('ja', preferences.read_settings(new)['language'])
        self.assertFalse(new.exists())
        self.assertEqual(content, old.read_text())

    def test_new_settings_take_precedence_over_legacy(self):
        for name, language in ((LEGACY_APP_NAME, 'ja'), (APP_NAME, 'en')):
            p = self.root / name / 'compact-ui.json'
            p.parent.mkdir()
            p.write_text(json.dumps({'language': language}))
        self.assertEqual({'language': 'en'}, preferences.read_settings(preferences.settings_path()))

    def test_invalid_new_settings_do_not_resurrect_legacy(self):
        for name, content in ((LEGACY_APP_NAME, '{"language":"ja"}'), (APP_NAME, '{broken')):
            p = self.root / name / 'compact-ui.json'
            p.parent.mkdir()
            p.write_text(content)
        self.assertEqual({}, preferences.read_settings(preferences.settings_path()))

    def test_custom_path_does_not_load_legacy(self):
        old = self.root / LEGACY_APP_NAME / 'compact-ui.json'
        old.parent.mkdir(); old.write_text('{"language":"ja"}')
        self.assertEqual({}, preferences.read_settings(self.root / 'custom.json'))

    def test_gui_launchers_are_branded_and_no_generation_cli_exists(self):
        root = Path(__file__).resolve().parent.parent
        for fn in ('gui.bat', 'gui.pyw'):
            content = (root / fn).read_text()
            self.assertIn(APP_NAME, content)
            self.assertNotIn('C++ Source Generator', content)
        for fn in ('generate.py', 'generate.bat', 'generate.ps1', 'gui.ps1', 'check_env.py'):
            self.assertFalse((root / fn).exists())

    def test_all_sources_parse_using_python_310_grammar(self):
        root = Path(__file__).resolve().parent.parent
        for p in [*root.rglob('*.py'), *root.rglob('*.pyw')]:
            with self.subTest(path=p.relative_to(root)):
                ast.parse(p.read_text(encoding='utf-8'), feature_version=(3, 10))

    @unittest.skipUnless(shutil.which('git'), 'git unavailable')
    def test_gitignore_excludes_local_data_but_keeps_sources_translations_and_docs(self):
        root = Path(__file__).resolve().parent.parent
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        shutil.copyfile(root / '.gitignore', self.root / '.gitignore')
        ignored = ['__pycache__/ui.cpython-313.pyc', 'internal/__pycache__/model.pyc', '.venv/pyvenv.cfg',
                   'build/app.exe', 'dist/app.zip', 'test-results.log', 'startup-error.log', '.gui_settings.json',
                   'compact-ui.json', 'compact-ui.tmp', '.cppgen-old', '.unrealsourcegen-new',
                   'Saved/UnrealSourceGenerator/Backups/one/manifest.json',
                   'Example/Saved/CppSourceGenerator/Backups/two/0.bin', '.idea/workspace.xml', '.DS_Store']
        tracked = ['README.md', 'README.ja.md', '.gitignore', 'gui.bat', 'gui.pyw', 'internal/model.py',
                   'internal/locales/en.json', 'internal/locales/ja.json', 'tests/test_naming.py',
                   'docs/TESTING.md', 'docs/main-en.png', 'Source/Game/Public/PlayerBase.h',
                   'Source/Game/Private/PlayerBase.cpp', 'Source/Game/Game.Build.cs',
                   'Demo.uproject', 'Plugins/MyPlugin/MyPlugin.uplugin']
        result = subprocess.run(['git', '-c', f'core.excludesFile={os.devnull}', 'check-ignore', '--stdin'],
                                cwd=self.root, input='\n'.join(ignored + tracked) + '\n',
                                capture_output=True, text=True, check=True)
        self.assertEqual(set(ignored), set(result.stdout.splitlines()))

    def test_readme_languages_are_short_and_use_new_names(self):
        root = Path(__file__).resolve().parent.parent
        for fn in ('README.md', 'README.ja.md'):
            text = (root / fn).read_text()
            self.assertLessEqual(len(text.splitlines()), 45)
            self.assertIn('github.com/mynameisGaku/UnrealSourceGenerator', text)
            self.assertIn('Source/MyGame/Public/PlayerBase.h', text)
            self.assertIn('Source/MyGame/Private/PlayerBase.cpp', text)
            self.assertIn('Saved/UnrealSourceGenerator/Backups', text)
            self.assertNotIn('CppSourceGenerator', text)
            self.assertNotIn('ATest.h', text)

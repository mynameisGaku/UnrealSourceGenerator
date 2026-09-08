from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from internal import model as m, templates
from tests.common import fixture, snapshot


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Project 日本語'
        self.up = fixture(self.root)
        self.project = m.load_project(self.up)
        self.target = next(t for t in self.project.targets if t.name == 'Game')

    def req(self, **kw):
        return replace(m.Request(self.target, 'Actor', 'TestActor'), **kw)

    def test_01_discovery_generic_project(self):
        self.assertEqual({'Game', 'EditorTools', 'Flat'}, {t.name for t in self.project.targets})
        self.assertEqual(self.project, m.load_project(self.root))

    def test_02_discovery_nested_plugin_and_module(self):
        p = self.root / 'Plugins/Vendor/PluginFolder'
        module = p / 'Source/Category/UnusualDirectory'
        module.mkdir(parents=True)
        (p / 'ActualPlugin.uplugin').write_text('{"Modules":[{"Name":"ExtModule","Type":"Editor"}]}')
        (module / 'ExtModule.Build.cs').write_text('')
        project = m.load_project(self.up)
        t = next(t for t in project.targets if t.name == 'ExtModule')
        self.assertEqual(module, t.folder)
        self.assertEqual('Editor', t.kind)
        self.assertEqual('Vendor/PluginFolder / ExtModule', t.label)

    def test_03_missing_project_does_not_fallback(self):
        with self.assertRaises(m.ValidationError):
            m.load_project(self.root / 'missing.uproject')

    def test_04_ambiguous_project_requires_file(self):
        (self.root / 'Second.uproject').write_text('{}')
        with self.assertRaises(m.ValidationError):
            m.load_project(self.root)
        self.assertEqual(self.up, m.load_project(self.up).file)

    def test_05_ancestor_detection(self):
        nested = self.root / 'Tools/UnrealSourceGenerator/internal'
        nested.mkdir(parents=True)
        self.assertEqual(self.up, m.find_project(nested))

    def test_06_corrupt_descriptor(self):
        self.up.write_text('{broken')
        with self.assertRaises(m.ValidationError):
            m.load_project(self.up)

    def test_07_prefixes_and_full_names(self):
        for value, tmpl, expected in [('Ship', 'Actor', 'AShip'), ('AShip', 'Actor', 'AShip'),
                                      ('Animation', 'Actor', 'AAnimation'), ('Mode', 'Enum', 'EMode'),
                                      ('EMode', 'PlainEnum', 'EMode'), ('Row', 'Struct', 'FRow'),
                                      ('Item', 'Interface', 'IItem'), ('UItem', 'Interface', 'IItem'),
                                      ('System', 'WorldSubsystem', 'USystem'), ('Utility', 'PlainClass', 'Utility')]:
            with self.subTest(value=value, template=tmpl):
                self.assertEqual(expected, m.type_name(value, tmpl))

    def test_08_empty_prefix_rejected_without_stripping_other_letters(self):
        self.assertEqual('AUBad', m.type_name('UBad', 'Actor'))
        self.assertEqual('AFPSCounter', m.type_name('FPSCounter', 'Actor'))
        for value, tmpl in [('A', 'Actor'), ('E', 'Enum'), ('F', 'Struct')]:
            with self.subTest(value=value), self.assertRaises(m.ValidationError):
                m.type_name(value, tmpl)

    def test_09_identifier_validation(self):
        for n in ('1bad', 'A B', 'A-B', '日本語', 'class', 'CON', '__Bad', '_Bad'):
            with self.subTest(name=n), self.assertRaises(m.ValidationError):
                m.type_name(n, 'PlainClass')

    def test_10_relative_folders(self):
        self.assertEqual('AI/Flight', m.normalized_folder(' AI\\./Flight '))
        for value in ('../x', 'X/../Y', '/outside', 'C:/outside', '\\\\server\\x', 'AUX', 'Bad.', 'x:a', 'Game/CON.txt'):
            with self.subTest(value=value), self.assertRaises(m.ValidationError):
                m.normalized_folder(value)

    def test_11_symlink_escape(self):
        outside = Path(self.temp.name) / 'Elsewhere'
        outside.mkdir()
        link = self.target.folder / 'Public/Link'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink permission unavailable')
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(folder='Link'))
        self.assertEqual([], list(outside.iterdir()))

    def test_12_preview_is_write_free(self):
        before = snapshot(self.root)
        options = {'with_tick': True}
        r = self.req(folder='New/Nested', options=options)
        m.build_plan(self.project, r)
        self.assertEqual(before, snapshot(self.root))
        self.assertFalse((self.target.folder / 'Public/New').exists())
        self.assertEqual({'with_tick': True}, options)

    def test_13_all_templates_all_layouts_preview_write_parity(self):
        for tmpl in templates.TEMPLATES:
            target = next(t for t in self.project.targets if t.name == ('EditorTools' if tmpl == 'EditorSubsystem' else 'Game'))
            for layout in m.LAYOUTS.values():
                with self.subTest(template=tmpl, layout=layout):
                    r = m.Request(target, tmpl, 'Sample' + tmpl + layout, folder='Matrix', layout=layout)
                    plan = m.build_plan(self.project, r)
                    receipt = m.commit(plan, allow_existing=True)
                    for c in plan.changes:
                        self.assertEqual(c.after, c.path.read_bytes())
                    if tmpl not in m.PLAIN:
                        h = next(c for c in plan.changes if c.role == 'header')
                        self.assertIn(f'"{h.path.stem}.generated.h"', h.content)
                    m.undo(receipt)

    def test_14_explicit_split_on_flat_module(self):
        target = next(t for t in self.project.targets if t.name == 'Flat')
        p = m.build_plan(self.project, self.req(target=target))
        m.commit(p)
        self.assertTrue((target.folder / 'Public/TestActor.h').is_file())
        self.assertTrue((target.folder / 'Private/TestActor.cpp').is_file())

    def test_15_auto_header_only_enum_struct_interface(self):
        for t in ('Enum', 'PlainEnum', 'Struct', 'PlainStruct', 'Interface'):
            with self.subTest(template=t):
                p = m.build_plan(self.project, self.req(template=t, name='Sample'))
                self.assertEqual(['header'], [c.role for c in p.changes])

    def test_16_tick_defaults_off(self):
        p = m.build_plan(self.project, self.req())
        h, c = p.changes
        self.assertNotIn('Tick(', h.content)
        self.assertIn('BeginPlay', h.content)
        self.assertIn('ATestActor::ATestActor()', c.content)

    def test_17_tick_requires_constructor(self):
        p = m.build_plan(self.project, self.req(options={'with_tick': True, 'with_constructor': False}))
        self.assertIn('ATestActor();', p.changes[0].content)
        self.assertIn('bCanEverTick = true', p.changes[1].content)

    def test_18_header_only_plain_class_inline(self):
        p = m.build_plan(self.project, self.req(template='PlainClass', options={'header_only': True}))
        self.assertEqual(1, len(p.changes))
        self.assertIn('TestActor() = default;', p.changes[0].content)

    def test_19_reflected_header_only_rejected(self):
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(options={'header_only': True}))

    def test_20_namespace_and_extra_includes(self):
        p = m.build_plan(self.project, self.req(template='PlainClass', options={'namespace': 'MyGame::AI', 'extra_includes': 'Extra.h, #include <vector>'}))
        for c in p.changes:
            self.assertIn('namespace MyGame::AI', c.content)
        self.assertLess(p.changes[0].content.index('Extra.h'), p.changes[0].content.index('namespace'))

    def test_21_namespace_rejected_on_reflected(self):
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(options={'namespace': 'X'}))
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(template='PlainClass', options={'namespace': 'X::class'}))

    def test_22_includes_before_generated(self):
        for template in ('Actor', 'Struct', 'Enum'):
            with self.subTest(template=template):
                p = m.build_plan(self.project, self.req(template=template, name='Sample', options={'extra_includes': 'Extra.h'}))
                includes = [line for line in p.changes[0].content.splitlines() if line.startswith('#include')]
                self.assertIn('#include "Extra.h"', includes)
                self.assertIn('.generated.h', includes[-1])

    def test_23_editor_dependency_is_previewed_and_public(self):
        ed = next(t for t in self.project.targets if t.name == 'EditorTools')
        p = m.build_plan(self.project, self.req(target=ed, template='EditorSubsystem', name='ToolSystem'))
        dep = next(c for c in p.changes if c.role == 'dependency')
        self.assertIn('PublicDependencyModuleNames.Add("EditorSubsystem")', dep.content)
        self.assertNotIn('"EditorSubsystem"', dep.before.decode())
        receipt = m.commit(p, allow_existing=True)
        m.undo(receipt)
        self.assertEqual(dep.before, dep.path.read_bytes())

    def test_24_editor_runtime_blocked(self):
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(template='EditorSubsystem', name='Tools'))

    def test_25_existing_paths_require_confirmation(self):
        p = m.build_plan(self.project, self.req())
        m.commit(p)
        p2 = m.build_plan(self.project, self.req(options={'with_tick': True}))
        with self.assertRaises(m.ValidationError):
            m.commit(p2)
        self.assertEqual(p.changes[0].after, p.changes[0].path.read_bytes())

    def test_26_snapshot_stale_existing_file(self):
        p = m.build_plan(self.project, self.req())
        m.commit(p)
        p2 = m.build_plan(self.project, self.req())
        p2.changes[0].path.write_text('// external edit')
        with self.assertRaises(m.ValidationError):
            m.commit(p2, allow_existing=True)
        self.assertEqual('// external edit', p2.changes[0].path.read_text())

    def test_27_snapshot_new_file_appeared(self):
        p = m.build_plan(self.project, self.req())
        p.changes[0].path.write_text('// keep')
        with self.assertRaises(m.ValidationError):
            m.commit(p)
        self.assertEqual('// keep', p.changes[0].path.read_text())

    def test_28_failed_second_write_rolls_back_first(self):
        p = m.build_plan(self.project, self.req(folder='Created'))
        before = snapshot(self.root)
        original = m._mkdir
        def fail(path, made):
            if path == p.changes[1].path.parent:
                raise OSError('injected write failure')
            original(path, made)
        with patch.object(m, '_mkdir', side_effect=fail), self.assertRaises(m.ValidationError):
            m.commit(p)
        self.assertEqual(before, snapshot(self.root))
        self.assertFalse(p.changes[0].path.parent.exists())

    def test_29_backup_and_undo_preserve_bytes(self):
        p = m.build_plan(self.project, self.req())
        old = b'\xef\xbb\xbf#pragma once\r\n// old\r\n'
        p.changes[0].path.write_bytes(old)
        p = m.build_plan(self.project, self.req())
        receipt = m.commit(p, allow_existing=True)
        self.assertTrue(receipt.backup.is_dir())
        self.assertEqual(old, (receipt.backup / '0.bin').read_bytes())
        self.assertTrue(p.changes[0].path.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'\r\n', p.changes[0].path.read_bytes())
        m.undo(receipt)
        self.assertEqual(old, p.changes[0].path.read_bytes())
        self.assertFalse(p.changes[1].path.exists())

    def test_30_undo_does_not_touch_edited_files(self):
        p = m.build_plan(self.project, self.req())
        receipt = m.commit(p)
        p.changes[1].path.write_text('// edited')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.undo(receipt)
        self.assertEqual(before, snapshot(self.root))

    def test_31_undo_new_files_and_folders(self):
        before = snapshot(self.root)
        p = m.build_plan(self.project, self.req(folder='New/Sub'))
        receipt = m.commit(p)
        m.undo(receipt)
        self.assertEqual(before, snapshot(self.root))
        self.assertFalse((self.target.folder / 'Public/New').exists())

    def test_32_alternate_layout_collision_never_deleted(self):
        p = m.build_plan(self.project, self.req(layout='public'))
        m.commit(p)
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(layout='split'))
        self.assertEqual(before, snapshot(self.root))

    def test_33_case_insensitive_header_collision(self):
        (self.target.folder / 'Public/testactor.h').write_text('// original')
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req())

    def test_34_missing_append_target(self):
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(options={'append_to': 'Missing.h'}))

    def test_35_append_reflected_with_required_include(self):
        m.commit(m.build_plan(self.project, self.req(name='BaseActor')))
        p = m.build_plan(self.project, self.req(template='Struct', name='Row', options={'append_to': 'BaseActor.h', 'with_struct_datatable': True}))
        h = p.changes[0].content
        self.assertIn('class GAME_API ABaseActor', h)
        self.assertIn('struct GAME_API FRow : public FTableRowBase', h)
        self.assertIn('#include "Engine/DataTable.h"', h)
        self.assertEqual(1, h.count('.generated.h'))
        self.assertLess(h.index('Engine/DataTable.h'), h.index('BaseActor.generated.h'))
        m.commit(p, allow_existing=True)
        self.assertEqual(p.changes[0].after, p.changes[0].path.read_bytes())

    def test_36_append_into_plain_adds_correct_generated(self):
        m.commit(m.build_plan(self.project, self.req(template='PlainClass', name='Shared', options={'header_only': True})))
        p = m.build_plan(self.project, self.req(template='Enum', name='Mode', options={'append_to': 'Shared.h'}))
        self.assertIn('Shared.generated.h', p.changes[0].content)
        self.assertNotIn('Mode.generated.h', p.changes[0].content)

    def test_37_append_duplicate_blocked(self):
        m.commit(m.build_plan(self.project, self.req(name='BaseActor')))
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(name='BaseActor', options={'append_to': 'BaseActor.h'}))

    def test_38_append_guard_stays_inside(self):
        h = self.target.folder / 'Public/Shared.h'
        h.write_text('#ifndef SHARED_H\n#define SHARED_H\n#include "CoreMinimal.h"\n\n#endif // SHARED_H\n')
        p = m.build_plan(self.project, self.req(template='PlainEnum', name='Mode', options={'append_to': 'Shared.h'}))
        text = p.changes[0].content
        self.assertLess(text.index('enum class EMode'), text.index('#endif'))

    def test_39_append_cpp_uses_existing_header(self):
        m.commit(m.build_plan(self.project, self.req(template='PlainStruct', name='Shared')))
        p = m.build_plan(self.project, self.req(template='Actor', name='Extra', options={'append_to': 'Shared.h'}))
        self.assertEqual('Shared.cpp', p.changes[1].path.name)
        self.assertTrue(p.changes[1].content.startswith('#include "Shared.h"'))

    def test_40_append_namespace_no_duplicate_includes(self):
        m.commit(m.build_plan(self.project, self.req(template='PlainEnum', name='Base')))
        p = m.build_plan(self.project, self.req(template='PlainClass', name='Extra', options={'namespace':'Tools', 'append_to':'Base.h', 'extra_includes':'Extra.h'}))
        text = p.changes[0].content
        self.assertEqual(1, text.count('#include "Extra.h"'))
        self.assertLess(text.index('Extra.h'), text.index('namespace Tools'))

    def test_41_module_scaffold_adds_target_entries(self):
        before = snapshot(self.root)
        p = m.scaffold_plan(self.project, 'Added', 'Runtime')
        self.assertEqual(before, snapshot(self.root))
        receipt = m.commit(p, allow_existing=True)
        project = m.load_project(self.up)
        self.assertIn('Added', [t.name for t in project.targets])
        for suffix in ('', 'Editor'):
            self.assertIn('ExtraModuleNames.Add("Added");', (self.root / 'Source' / f'Demo{suffix}.Target.cs').read_text())
        m.undo(receipt)
        after = {k:v for k,v in snapshot(self.root).items() if not k.startswith('Saved/')}
        self.assertEqual(before, after)

    def test_42_editor_module_only_editor_target(self):
        p = m.scaffold_plan(self.project, 'AddedEd', 'Editor')
        targets = [c for c in p.changes if c.role == 'target']
        self.assertEqual(['DemoEditor.Target.cs'], [c.path.name for c in targets])

    def test_43_plugin_scaffold_and_extra_module(self):
        receipt = m.commit(m.scaffold_plan(self.project, 'MyPlugin', 'Runtime', plugin=True), allow_existing=True)
        project = m.load_project(self.up)
        target = next(t for t in project.targets if t.name == 'MyPlugin')
        self.assertTrue(target.plugin)
        p = m.scaffold_plan(project, 'PluginEditor', 'Editor', plugin_descriptor=target.descriptor)
        self.assertFalse(any(c.role == 'target' for c in p.changes))
        m.commit(p, allow_existing=True)
        mods = m.read_json(target.descriptor)['Modules']
        self.assertIn('PluginEditor', [d['Name'] for d in mods])

    def test_44_scaffold_rejects_existing(self):
        with self.assertRaises(m.ValidationError):
            m.scaffold_plan(self.project, 'Game', 'Runtime')

    def test_45_unparseable_target_does_not_write(self):
        (self.root / 'Source/Demo.Target.cs').write_text('class Unknown {}')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.scaffold_plan(self.project, 'Added', 'Runtime')
        self.assertEqual(before, snapshot(self.root))

    def test_46_blueprint_project_primary_module(self):
        p = self.root / 'Blueprint'
        p.mkdir()
        up = p / 'Blueprint.uproject'; up.write_text('{"FileVersion":3}')
        project = m.load_project(up)
        plan = m.scaffold_plan(project, 'Blueprint', 'Runtime')
        self.assertEqual(2, sum(c.role == 'target' for c in plan.changes))
        self.assertTrue(any('IMPLEMENT_PRIMARY_GAME_MODULE' in c.content for c in plan.changes))
        m.commit(plan, allow_existing=True)
        self.assertEqual(1, len(m.load_project(up).targets))

    def test_47_full_struct_features(self):
        p = m.build_plan(self.project, self.req(template='Struct', name='Row', options={
            'with_struct_hash':True, 'with_struct_datatable':True, 'with_struct_netserialize':True,
            'with_struct_tostring':True}))
        for token in ('operator==', 'GetTypeHash', 'FTableRowBase', 'NetSerialize', 'ToString', '!Ar.IsError()'):
            self.assertIn(token, p.changes[0].content)

    def test_48_no_api_and_bp(self):
        p = m.build_plan(self.project, self.req(options={'with_api':False, 'blueprint_type':True}))
        self.assertNotIn('GAME_API', p.changes[0].content)
        self.assertIn('UCLASS(BlueprintType, Blueprintable)', p.changes[0].content)

    def test_49_skip_generated_and_hidden_folders(self):
        for name in ('Saved', 'Binaries', '.git'):
            (self.target.folder / 'Public' / name).mkdir()
        (self.target.folder / 'Public/AI').mkdir()
        self.assertEqual(('', 'AI'), m.existing_folders(self.target))

    def test_50_deleted_project_stops_generation(self):
        self.up.unlink()
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req())

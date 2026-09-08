"""Regression tests for automatic names and module/plugin/empty-folder additions."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from internal import model as m, templates
from tests.common import fixture, snapshot


class AdditionModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Project 日本語'
        self.up = fixture(self.root)
        self.project = m.load_project(self.up)
        self.target = next(t for t in self.project.targets if t.name == 'Game')

    def req(self, **kw):
        return replace(m.Request(self.target, 'Actor', 'Test'), **kw)

    def plugin(self, name='ContentOnly', modules=None):
        p = self.root / 'Plugins/Vendor' / name
        p.mkdir(parents=True)
        descriptor = p / f'{name}.uplugin'
        data = {'FileVersion': 3, 'Version': 12, 'CanContainContent': True,
                'Description': '保持する日本語', 'Extra': {'Untouched': True}}
        if modules is not None:
            data['Modules'] = modules
        descriptor.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return descriptor

    def test_actor_test_is_atest_in_all_emitted_locations(self):
        req = self.req(folder='Actors/Nested')
        plan = m.build_plan(self.project, req)
        header, cpp = plan.changes
        self.assertEqual('ATest', plan.name)
        self.assertEqual('Test.h', header.path.name)
        self.assertEqual('Test.cpp', cpp.path.name)
        self.assertIn('class GAME_API ATest : public AActor', header.content)
        self.assertIn('ATest();', header.content)
        self.assertIn('#include "Test.generated.h"', header.content)
        self.assertIn('#include "Actors/Nested/Test.h"', cpp.content)
        self.assertIn('ATest::ATest()', cpp.content)
        before = snapshot(self.root)
        self.assertNotIn('Source/Game/Public/Actors/Nested/Test.h', before)
        receipt = m.commit(plan)
        for change in plan.changes:
            self.assertEqual(change.after, change.path.read_bytes())
        self.assertEqual('Test', req.name)
        m.undo(receipt)
        self.assertEqual(before, snapshot(self.root))

    def test_correct_prefix_never_added_twice_across_all_templates(self):
        for template in templates.TEMPLATES:
            with self.subTest(template=template):
                name = m.required_prefix(template) + 'Test'
                self.assertEqual(name, m.type_name('Test', template))
                self.assertEqual(name, m.type_name(name, template))

    def test_word_initials_not_mistaken_for_a_prefix(self):
        for template, name, expected in (
            ('Actor', 'Animation', 'AAnimation'), ('UObject', 'User', 'UUser'),
            ('Enum', 'Enemy', 'EEnemy'), ('Struct', 'Fighter', 'FFighter'),
            ('Interface', 'Item', 'IItem')):
            with self.subTest(template=template):
                self.assertEqual(expected, m.type_name(name, template))

    def test_other_leading_capitals_belong_to_the_base_name(self):
        self.assertEqual('AFPSCounter', m.type_name('FPSCounter', 'Actor'))
        self.assertEqual('UIOSManager', m.type_name('IOSManager', 'UObject'))
        self.assertEqual('EAIDifficulty', m.type_name('AIDifficulty', 'Enum'))
        self.assertEqual('XMLReader', m.type_name('XMLReader', 'PlainClass'))

    def test_prefixed_names_with_number_or_underscore_not_doubled(self):
        for template in templates.TEMPLATES:
            prefix = m.required_prefix(template)
            if prefix:
                for tail in ('2D', '_Test', 'Test2'):
                    with self.subTest(template=template, tail=tail):
                        self.assertEqual(prefix + tail, m.type_name(prefix + tail, template))
        self.assertEqual('I2D', m.type_name('U2D', 'Interface'))

    def test_output_length_cannot_bypass_identifier_limit(self):
        with self.assertRaises(m.ValidationError):
            m.type_name('T' * 180, 'Actor')
        self.assertEqual('A' + 'T' * 179, m.type_name('A' + 'T' * 179, 'Actor'))

    def test_interface_names_and_generated_include_stay_consistent(self):
        for name in ('Test', 'ITest', 'UTest'):
            with self.subTest(name=name):
                plan = m.build_plan(self.project, self.req(template='Interface', name=name))
                self.assertEqual('ITest', plan.name)
                self.assertEqual(1, len(plan.changes))
                self.assertEqual('Test.h', plan.changes[0].path.name)
                self.assertIn('class UTest : public UInterface', plan.changes[0].content)
                self.assertIn('class GAME_API ITest', plan.changes[0].content)
                self.assertIn('"Test.generated.h"', plan.changes[0].content)

    def test_base_and_full_names_share_collision_detection(self):
        plan = m.build_plan(self.project, self.req())
        m.commit(plan)
        full = m.build_plan(self.project, self.req(name='ATest'))
        self.assertEqual(2, len(full.modified))
        with self.assertRaises(m.ValidationError):
            m.commit(full)
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, self.req(name='Test', folder='Elsewhere'))

    def test_append_uses_resolved_name_and_guards_duplicates(self):
        m.commit(m.build_plan(self.project, self.req(name='Shared')))
        req = self.req(options={'append_to': 'Shared.h'})
        plan = m.build_plan(self.project, req)
        m.commit(plan, allow_existing=True)
        header = self.target.folder / 'Public/Shared.h'
        self.assertIn('class GAME_API ATest', header.read_text())
        self.assertEqual(1, header.read_text().count('.generated.h'))
        self.assertFalse((header.parent / 'Test.h').exists())
        with self.assertRaises(m.ValidationError):
            m.build_plan(self.project, replace(req, name='ATest'))

    def test_folder_only_plan_creates_no_files_for_any_layout(self):
        for layout, sides in (('split', ('Public', 'Private')), ('flat', ('',)),
                              ('public', ('Public',)), ('private', ('Private',))):
            with self.subTest(layout=layout):
                before = snapshot(self.root)
                plan = m.folder_plan(self.project, self.target, '空フォルダ/AI', layout)
                self.assertFalse(plan.changes)
                self.assertFalse((self.target.folder / '空フォルダ').exists())
                receipt = m.commit(plan)
                self.assertEqual(before, snapshot(self.root))
                for side in sides:
                    self.assertTrue((self.target.folder / side / '空フォルダ/AI').is_dir())
                self.assertIn('空フォルダ/AI', m.existing_folders(self.target, layout))
                m.undo(receipt)
                for side in sides:
                    self.assertFalse((self.target.folder / side / '空フォルダ').exists())

    def test_folder_already_exists_has_no_changes_to_undo(self):
        for side in ('Public', 'Private'):
            p = self.target.folder / side / 'Existing'
            p.mkdir()
            (p / 'Keep.txt').write_text('unchanged')
        before = snapshot(self.root)
        receipt = m.commit(m.folder_plan(self.project, self.target, 'Existing', 'split'))
        self.assertFalse(receipt.created_dirs)
        m.undo(receipt)
        self.assertEqual(before, snapshot(self.root))

    def test_folder_undo_preserves_existing_half_of_split(self):
        existing = self.target.folder / 'Public/New'
        existing.mkdir()
        receipt = m.commit(m.folder_plan(self.project, self.target, 'New', 'split'))
        m.undo(receipt)
        self.assertTrue(existing.is_dir())
        self.assertFalse((self.target.folder / 'Private/New').exists())

    def test_folder_failure_rolls_back_all_new_directories(self):
        original = m._mkdir
        def fail_private(path, made):
            if 'Private' in path.parts:
                raise OSError('injected mkdir failure')
            original(path, made)
        plan = m.folder_plan(self.project, self.target, 'New/Nested', 'split')
        with patch.object(m, '_mkdir', side_effect=fail_private):
            with self.assertRaises(m.ValidationError):
                m.commit(plan)
        self.assertFalse((self.target.folder / 'Public/New').exists())
        self.assertFalse((self.target.folder / 'Private/New').exists())

    def test_file_as_folder_is_rejected_before_any_write(self):
        (self.target.folder / 'Private/Occupied').write_text('keep')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.folder_plan(self.project, self.target, 'Occupied/Nested', 'split')
        self.assertFalse((self.target.folder / 'Public/Occupied').exists())
        self.assertEqual(before, snapshot(self.root))

    def test_folder_undo_refuses_external_file_or_empty_directory(self):
        for is_file in (True, False):
            receipt = m.commit(m.folder_plan(self.project, self.target, 'New/Nested', 'split'))
            public = self.target.folder / 'Public/New/Nested'
            external = public / 'External'
            if is_file:
                external.write_text('keep me')
            else:
                external.mkdir()
            with self.assertRaises(m.ValidationError):
                m.undo(receipt)
            self.assertTrue(public.is_dir())
            self.assertTrue((self.target.folder / 'Private/New/Nested').is_dir())
            self.assertTrue(external.exists())
            external.unlink() if is_file else external.rmdir()
            m.undo(receipt)

    def test_folder_undo_failure_restores_removed_directories(self):
        receipt = m.commit(m.folder_plan(self.project, self.target, 'New/Nested', 'split'))
        original = Path.rmdir
        def failure(path):
            if path == self.target.folder / 'Public/New/Nested':
                raise OSError('injected undo failure')
            return original(path)
        with patch.object(Path, 'rmdir', failure):
            with self.assertRaises(m.ValidationError):
                m.undo(receipt)
        for side in ('Public', 'Private'):
            self.assertTrue((self.target.folder / side / 'New/Nested').is_dir())
        m.undo(receipt)

    def test_folder_rejects_invalid_names_and_symlinks(self):
        for name in ('', '../Outside', '/absolute', 'C:/Absolute', 'Game/CON', 'Bad.'):
            with self.subTest(name=name), self.assertRaises(m.ValidationError):
                m.folder_plan(self.project, self.target, name, 'split')
        outside = Path(self.temp.name) / 'Outside'
        outside.mkdir()
        try:
            (self.target.folder / 'Public/Link').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink permission unavailable')
        with self.assertRaises(m.ValidationError):
            m.folder_plan(self.project, self.target, 'Link/New', 'split')
        self.assertFalse(list(outside.iterdir()))

    def test_commit_rechecks_folder_obstacle_after_planning(self):
        plan = m.folder_plan(self.project, self.target, 'Later/Nested', 'split')
        (self.target.folder / 'Private/Later').write_text('new external file')
        with self.assertRaises(m.ValidationError):
            m.commit(plan)
        self.assertFalse((self.target.folder / 'Public/Later').exists())

    def test_flat_folder_choices_do_not_mix_public_private_trees(self):
        for path in ('Public/VisiblePublic', 'Private/VisiblePrivate', 'RootFolder'):
            (self.target.folder / path).mkdir()
        self.assertEqual(('', 'RootFolder'), m.existing_folders(self.target, 'flat'))
        self.assertEqual(('', 'VisiblePrivate'), m.existing_folders(self.target, 'private'))
        self.assertEqual(('', 'VisiblePublic'), m.existing_folders(self.target, 'public'))

    def test_content_only_plugin_can_receive_its_first_module(self):
        descriptor = self.plugin()
        original = descriptor.read_bytes()
        project = m.load_project(self.up)
        self.assertNotIn('ContentOnly', {t.name for t in project.targets})
        self.assertEqual(descriptor, m.available_plugins(project)['Vendor/ContentOnly'])
        before_project = self.up.read_bytes()
        plan = m.scaffold_plan(project, 'FirstCode', 'Runtime', plugin_descriptor=descriptor)
        self.assertEqual(original, descriptor.read_bytes())
        self.assertFalse(any(c.role == 'target' for c in plan.changes))
        receipt = m.commit(plan, allow_existing=True)
        data = m.read_json(descriptor)
        self.assertEqual('保持する日本語', data['Description'])
        self.assertEqual({'Untouched': True}, data['Extra'])
        self.assertEqual('FirstCode', data['Modules'][0]['Name'])
        self.assertEqual(before_project, self.up.read_bytes())
        self.assertIn('FirstCode', {t.name for t in m.load_project(self.up).targets})
        m.undo(receipt)
        self.assertEqual(original, descriptor.read_bytes())
        self.assertFalse((descriptor.parent / 'Source').exists())

    def test_module_rejects_registered_name_without_source(self):
        self.plugin(modules=[{'Name': 'DeclaredOnly', 'Type': 'Runtime'}])
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.scaffold_plan(self.project, 'declaredonly', 'Runtime')
        self.assertEqual(before, snapshot(self.root))

    def test_module_rechecks_stale_project_for_duplicate_source(self):
        m.commit(m.scaffold_plan(self.project, 'Added', 'Runtime'), allow_existing=True)
        with self.assertRaises(m.ValidationError):
            m.scaffold_plan(self.project, 'Added', 'Runtime')

    def test_plugin_name_collision_is_detected_in_nested_folder(self):
        self.plugin('ExistingPlugin')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.scaffold_plan(self.project, 'existingplugin', 'Runtime', plugin=True)
        self.assertEqual(before, snapshot(self.root))

    def test_plugin_registration_enables_existing_entry_without_duplicate(self):
        data = m.read_json(self.up)
        data['Plugins'] = [{'Name': 'NewPlugin', 'Enabled': False, 'Optional': True}]
        self.up.write_text(json.dumps(data))
        m.commit(m.scaffold_plan(self.project, 'NewPlugin', 'Runtime', plugin=True), allow_existing=True)
        plugins = m.read_json(self.up)['Plugins']
        self.assertEqual([{'Name': 'NewPlugin', 'Enabled': True, 'Optional': True}], plugins)

    def test_new_plugin_module_folder_and_actor_full_workflow(self):
        m.commit(m.scaffold_plan(self.project, 'FlightTools', 'Runtime', plugin=True), allow_existing=True)
        project = m.load_project(self.up)
        target = next(t for t in project.targets if t.name == 'FlightTools')
        m.commit(m.scaffold_plan(project, 'FlightEditor', 'Editor', plugin_descriptor=target.descriptor), allow_existing=True)
        project = m.load_project(self.up)
        m.commit(m.folder_plan(project, target, 'Game/Actors', 'split'))
        plan = m.build_plan(project, m.Request(target, 'Actor', 'Test', folder='Game/Actors'))
        m.commit(plan)
        self.assertIn('class FLIGHTTOOLS_API ATest', plan.changes[0].path.read_text())
        self.assertTrue((target.folder / 'Private/Game/Actors/Test.cpp').is_file())
        self.assertEqual({'FlightTools', 'FlightEditor'}, set(m._module_types(m.read_json(target.descriptor))))

    def test_scaffold_snapshot_is_the_same_bytes_that_were_parsed(self):
        original = m.read_json_snapshot
        calls = 0
        def concurrent_read(path):
            nonlocal calls
            data, raw = original(path)
            if path == self.up:
                calls += 1
                # First read: load_project. Second read: mutation-plan snapshot.
                if calls == 2:
                    edited = dict(data, Description='External edit during planning')
                    path.write_text(json.dumps(edited))
            return data, raw
        with patch.object(m, 'read_json_snapshot', side_effect=concurrent_read):
            plan = m.scaffold_plan(self.project, 'SnapshotTest', 'Runtime')
        with self.assertRaises(m.ValidationError):
            m.commit(plan, allow_existing=True)
        self.assertEqual('External edit during planning', m.read_json(self.up)['Description'])
        self.assertFalse((self.root / 'Source/SnapshotTest').exists())

    def test_invalid_descriptor_modules_fails_without_partial_creation(self):
        self.plugin(modules='not a module array')
        before = snapshot(self.root)
        with self.assertRaises(m.ValidationError):
            m.scaffold_plan(self.project, 'NewModule', 'Runtime')
        self.assertEqual(before, snapshot(self.root))
        self.assertFalse((self.root / 'Source/NewModule').exists())

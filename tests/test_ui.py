from pathlib import Path
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk

from internal import model, ui
from tests.common import fixture, snapshot


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'GUI display unavailable')
class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.up = fixture(self.root / 'Project')
        self.errors = []
        for name in ('showerror', 'showinfo', 'showwarning'):
            p = patch.object(ui.messagebox, name, side_effect=lambda *a, **k: self.errors.append(a))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(ui.messagebox, 'askyesno', return_value=False)
        self.ask = p.start(); self.addCleanup(p.stop)
        self.app = ui.App(self.up, self.root / 'settings.json')
        self.app.var_target.set('Game'); self.app.on_target_changed()
        self.app.update()
        self.addCleanup(self.close_app)

    def close_app(self):
        try:
            if self.app.winfo_exists():
                self.app.destroy()
        except tk.TclError:
            pass

    def name(self, value='Ship'):
        self.app.var_name.set(value)
        self.app.refresh_preview()
        self.app.update()

    def dialog(self):
        self.app.open_options(); self.app.update()
        return next(iter(self.app._dialogs))

    def walk(self, widget):
        for c in widget.winfo_children():
            yield c
            yield from self.walk(c)

    def test_01_compact_geometry(self):
        self.assertLessEqual(self.app.winfo_width(), self.app.px(910))
        self.assertLessEqual(self.app.winfo_height(), self.app.px(520))
        self.assertLess(self.app.form.winfo_width(), self.app.px(300))

    def test_02_single_preview_notebook_no_dashboard(self):
        books = [w for w in self.walk(self.app) if isinstance(w, ttk.Notebook)]
        self.assertEqual([self.app.tabs], books)
        labels = [str(w.cget('text')) for w in self.walk(self.app) if isinstance(w, ttk.Label)]
        self.assertFalse(any(s in '\n'.join(labels) for s in ('STUDIO', 'ステップ', '入力してください', 'UNREAL ENGINE', '種類別')))
        self.assertEqual(5, len(self.app.inputs))

    def test_03_preview_visible_before_name(self):
        self.assertTrue(self.app.tabs.winfo_ismapped())
        self.assertEqual('', self.app.views['header'].content)
        self.assertTrue(self.app.generate_button.instate(['disabled']))
        self.assertEqual('', self.app.var_status.get())

    def test_04_name_live_preview_and_prefix(self):
        self.name()
        self.assertEqual('AShip', self.app.plan.name)
        self.assertIn('class GAME_API AShip', self.app.views['header'].content)
        self.assertTrue(self.app.generate_button.instate(['!disabled']))
        self.assertFalse((self.up.parent / 'Source/Game/Public/AShip.h').exists())

    def test_05_invalid_name_clears_stale_preview(self):
        self.name()
        self.name('Bad Name')
        self.assertEqual('', self.app.views['header'].content)
        self.assertTrue(self.app.generate_button.instate(['disabled']))
        self.assertEqual('name', self.app._error.field)

    def test_06_enum_hides_cpp_tab(self):
        self.app.var_template.set('Enum'); self.name('Mode')
        self.assertEqual('hidden', self.app.tabs.tab(self.app.views['cpp'], 'state'))
        self.assertIn('enum class EMode', self.app.views['header'].content)
        self.app.var_template.set('Actor'); self.name('Ship')
        self.assertEqual('normal', self.app.tabs.tab(self.app.views['cpp'], 'state'))

    def test_07_template_switch_updates_output_prefix_not_input(self):
        self.name('Ship')
        self.app.var_template.set('ActorComponent')
        self.app.refresh_preview()
        self.assertEqual('Ship', self.app.var_name.get())
        self.assertIn('class GAME_API UShip', self.app.views['header'].content)

    def test_08_template_filter_no_separate_search_box(self):
        self.app.var_template.set('World')
        self.app.filter_templates()
        # World is a valid alias, so the full list is intentionally retained.
        self.assertIn('WorldSubsystem', self.app.inputs['template']['values'])
        self.app.var_template.set('Subsys')
        self.app.filter_templates()
        self.assertTrue(all('Subsys' in t for t in self.app.inputs['template']['values']))

    def test_09_actor_options_only_relevant(self):
        d = self.dialog()
        self.assertEqual({'with_api', 'blueprint_type', 'with_constructor', 'with_beginplay', 'with_tick'}, set(d.checks))
        self.assertFalse(d.vars['with_tick'].get())
        d.close()

    def test_10_enum_options_no_actor_checkboxes(self):
        self.app.var_template.set('Enum')
        d = self.dialog()
        self.assertEqual({'with_enum_conversion'}, set(d.checks))
        d.close()

    def test_11_options_cancel_is_nonmutating(self):
        before = dict(self.app.options)
        d = self.dialog()
        d.vars['with_tick'].set(True)
        d.vars['extra_includes'].set('Extra.h')
        d.close()
        self.assertEqual(before, self.app.options)

    def test_12_options_apply_updates_preview(self):
        self.name()
        d = self.dialog()
        d.vars['with_constructor'].set(False)
        d.vars['with_tick'].set(True)
        self.assertTrue(d.vars['with_constructor'].get())
        d.apply()
        self.assertFalse(self.app._dialogs)
        self.assertIn('Tick(float', self.app.views['header'].content)
        self.assertIn('bCanEverTick = true', self.app.views['cpp'].content)
        self.assertEqual([], self.errors)

    def test_13_options_defaults_restore(self):
        d = self.dialog()
        d.vars['with_tick'].set(True)
        d.vars['extra_includes'].set('Extra.h')
        d.reset()
        self.assertFalse(d.vars['with_tick'].get())
        self.assertEqual('', d.vars['extra_includes'].get())
        d.close()

    def test_14_no_unsupported_namespace_leaks(self):
        self.app.var_template.set('PlainClass')
        self.app.options['namespace'] = 'Tools'
        self.app.var_template.set('Actor')
        self.name('Ship')
        self.assertEqual('', self.app.options['namespace'])
        self.assertIsNotNone(self.app.plan)
        self.app.var_template.set('PlainClass')
        self.assertEqual('Tools', self.app.options['namespace'])

    def test_15_module_switch_clears_folder_and_append(self):
        self.app.var_folder.set('Nested')
        self.app.options['append_to'] = 'Shared.h'
        self.app.var_target.set('Flat'); self.app.on_target_changed()
        self.assertEqual('', self.app.var_folder.get())
        self.assertEqual('', self.app.options['append_to'])
        self.assertEqual(self.app.layout_caption('flat'), self.app.var_layout.get())

    def test_16_generation_matches_preview_no_done_dialog(self):
        self.name()
        self.app.on_generate()
        self.assertEqual([], self.ask.call_args_list)
        self.assertEqual(self.app.tr('Generated {name}.', name='AShip'), self.app.var_status.get())
        self.assertEqual(self.app.tr('Generated'), self.app.generate_button.cget('text'))
        self.assertEqual('Ship', self.app.var_name.get())
        for c in self.app.last_receipt.plan.changes:
            self.assertEqual(c.after, c.path.read_bytes())
        self.assertTrue(self.app.views['header'].content)
        self.assertTrue(self.app.generate_button.instate(['disabled']))

    def test_17_enter_shortcuts_present(self):
        self.assertTrue(self.app.bind('<Control-Return>'))
        self.assertTrue(self.app.bind('<Control-g>'))

    def test_18_overwrite_decline_preserves_existing(self):
        self.name()
        self.app.on_generate()
        before = snapshot(self.up.parent)
        self.app.options['with_tick'] = True
        self.app.on_generate()
        self.assertEqual(before, snapshot(self.up.parent))
        self.assertEqual(1, self.ask.call_count)

    def test_19_overwrite_accept_backup_and_undo(self):
        self.name(); self.app.on_generate()
        original = self.app.last_receipt.plan.changes[0].path.read_bytes()
        self.ask.return_value = True
        self.app.options['with_tick'] = True
        self.app.on_generate()
        self.assertIsNotNone(self.app.last_receipt.backup)
        self.app.on_undo()
        self.assertEqual(original, (self.up.parent / 'Source/Game/Public/AShip.h').read_bytes())

    def test_20_undo_refuses_external_edit(self):
        self.name(); self.app.on_generate()
        self.ask.return_value = True
        path = self.app.last_receipt.plan.changes[0].path
        path.write_text('// externally edited')
        self.app.on_undo()
        self.assertTrue(self.errors)
        self.assertEqual('// externally edited', path.read_text())

    def test_21_copy_actual_preview(self):
        self.name()
        v = self.app.views['header']
        v.copy_all()
        self.assertEqual(v.content, self.app.clipboard_get())

    def test_22_wrap_optional_and_default_on(self):
        v = self.app.views['header']
        self.assertEqual('word', str(v.text.cget('wrap')))
        v.wrap.set(False); v.toggle_wrap()
        self.app.update()
        self.assertEqual('none', str(v.text.cget('wrap')))
        self.assertTrue(v.horizontal.winfo_ismapped())

    def test_23_tooltip_delayed_canceled_safely(self):
        tip = ui.ToolTip(self.app.name_entry, '名前の説明')
        tip.schedule()
        self.assertIsNotNone(tip.timer)
        tip.hide()
        self.assertIsNone(tip.timer)
        tip.show(); self.app.update()
        self.assertIsNotNone(tip.tip)
        self.assertGreaterEqual(tip.tip.winfo_rootx(), 0)
        tip.hide()
        self.assertIsNone(tip.tip)

    def test_24_shutdown_with_pending_tooltip_and_preview(self):
        tip = ui.ToolTip(self.app.name_entry, '説明')
        tip.schedule()
        self.app.var_name.set('FastTyping')
        self.app.destroy()
        self.assertTrue(self.app._closed)
        self.assertIsNone(self.app._timer)
        self.assertIsNone(tip.timer)

    def test_25_settings_saved_and_old_geometry_ignored(self):
        self.app.var_folder.set('AI')
        self.app.save_settings()
        state = json.loads(self.app.state_path.read_text())
        self.assertEqual('AI', state['folder'])
        self.assertNotIn('geometry', state)
        state['geometry'] = '1440x960'
        self.app.state_path.write_text(json.dumps(state))
        self.app.destroy()
        self.app = ui.App(self.up, self.root / 'settings.json')
        self.app.update()
        self.assertEqual('AI', self.app.var_folder.get())
        self.assertLess(self.app.winfo_width(), self.app.px(920))

    def test_26_project_change_resets_module(self):
        other = self.root / 'Other'; other.mkdir()
        up = other / 'Other.uproject'; up.write_text('{}')
        with patch.object(ui.filedialog, 'askopenfilename', return_value=str(up)):
            self.app.browse_project()
        self.assertEqual(up, self.app.project.file)
        self.assertEqual('', self.app.var_target.get())
        self.assertTrue(self.app.generate_button.instate(['disabled']))
        self.assertTrue(self.app.tools_button.instate(['!disabled']))

    def test_27_browse_cancel_preserves_project(self):
        with patch.object(ui.filedialog, 'askopenfilename', return_value=''):
            self.app.browse_project()
        self.assertEqual(self.up, self.app.project.file)

    def test_28_reload_keeps_options_and_undo(self):
        self.name(); self.app.on_generate()
        receipt = self.app.last_receipt
        self.app.options['with_tick'] = True
        self.app.reload_project()
        self.assertTrue(self.app.options['with_tick'])
        self.assertIs(receipt, self.app.last_receipt)

    def test_29_editor_dependency_has_own_preview_tab(self):
        self.app.var_target.set('EditorTools'); self.app.on_target_changed()
        self.app.var_template.set('EditorSubsystem'); self.name('Tools')
        self.assertEqual('normal', self.app.tabs.tab(self.app.views['dependency'], 'state'))
        self.assertIn('EditorSubsystem', self.app.views['dependency'].content)

    def test_30_background_update_success(self):
        with patch.object(ui.platform_tools, 'update_project', return_value='更新完了'):
            self.app.run_update()
            self.assertTrue(self.app._busy)
            self.assertTrue(self.app.generate_button.instate(['disabled']))
            deadline = time.monotonic() + 2
            while self.app._busy and time.monotonic() < deadline:
                self.app.update(); time.sleep(.015)
        self.assertFalse(self.app._busy)
        self.assertEqual('更新完了', self.app.var_status.get())

    def test_31_scaffold_dialog_real_module(self):
        self.ask.return_value = True
        self.app.open_scaffold(False)
        d = next(iter(self.app._dialogs))
        d.name.set('NewModule'); d.apply()
        self.assertFalse(self.app._dialogs)
        self.assertEqual('NewModule', self.app.current_target().name)
        self.assertTrue((self.up.parent / 'Source/NewModule/NewModule.Build.cs').exists())
        self.assertIsNotNone(self.app.last_receipt)
        self.assertEqual([], self.errors)

    def test_32_scaffold_dialog_real_plugin(self):
        self.ask.return_value = True
        self.app.open_scaffold(True)
        d = next(iter(self.app._dialogs))
        d.name.set('NewPlugin'); d.apply()
        self.assertEqual('NewPlugin / NewPlugin', self.app.var_target.get())
        self.assertTrue((self.up.parent / 'Plugins/NewPlugin/NewPlugin.uplugin').exists())
        self.assertEqual([], self.errors)

    def test_33_no_cli_distribution(self):
        root = Path(ui.__file__).resolve().parent.parent
        for name in ('generate.bat', 'generate.ps1', 'generate.py', 'gui.ps1', 'test.bat', 'check_env.py'):
            self.assertFalse((root / name).exists())
        self.assertNotIn('argparse', (root / 'internal/model.py').read_text())
        self.assertTrue((root / 'gui.pyw').is_file())

    def test_34_buttons_have_real_commands(self):
        for w in self.walk(self.app):
            if isinstance(w, ttk.Button):
                with self.subTest(button=w.cget('text')):
                    self.assertTrue(w.cget('command'))

    def test_35_form_controls_inside_window(self):
        self.app.geometry(f'{self.app.px(780)}x{self.app.px(510)}')
        self.app.update()
        for w in (*self.app.inputs.values(), self.app.advanced_button, self.app.generate_button):
            with self.subTest(widget=str(w)):
                self.assertGreaterEqual(w.winfo_rootx(), self.app.winfo_rootx())
                self.assertLessEqual(w.winfo_rootx()+w.winfo_width(), self.app.winfo_rootx()+self.app.winfo_width())
                self.assertLessEqual(w.winfo_rooty()+w.winfo_height(), self.app.winfo_rooty()+self.app.winfo_height())

    def test_36_long_name_does_not_resize_window(self):
        width = self.app.winfo_width()
        self.name('My' + 'VeryLong' * 15)
        self.assertIsNotNone(self.app.plan)
        self.assertEqual(width, self.app.winfo_width())
        self.assertLess(len(self.app.tabs.tab(self.app.views['header'], 'text')), 32)

    def test_37_advanced_settings_apply_without_name(self):
        d = self.dialog()
        d.vars['with_tick'].set(True); d.apply()
        self.assertFalse(self.app._dialogs)
        self.assertTrue(self.app.options['with_tick'])
        self.assertEqual([], self.errors)

    def test_38_generate_blocked_while_modal(self):
        self.name()
        d = self.dialog()
        self.app.on_generate()
        self.assertIsNone(self.app.last_receipt)
        d.close()

    def test_39_folder_typing_not_discarded(self):
        self.app.var_folder.set('New/Folder')
        self.app.refresh_folder_choices()
        self.assertEqual('New/Folder', self.app.var_folder.get())

    def test_40_preview_gutter_and_long_code(self):
        self.name('FlightMovementComponent')
        view = self.app.views['header']
        self.app.update()
        view.redraw()
        self.assertTrue(view.gutter.find_all())
        view.text.yview_moveto(1.0)
        self.app.update()
        self.assertTrue(view.gutter.find_all())

    def test_41_name_is_not_rewritten_on_focus_out_or_generate(self):
        self.name('Test')
        self.app.name_entry.event_generate('<FocusOut>')
        self.app.update()
        self.assertEqual('Test', self.app.var_name.get())
        self.app.on_generate()
        self.assertEqual('Test', self.app.var_name.get())
        self.assertEqual('ATest', self.app.last_receipt.plan.name)
        self.assertTrue((self.up.parent / 'Source/Game/Public/ATest.h').exists())
        self.assertEqual([], self.errors)

    def test_42_type_switch_only_recomputes_output(self):
        self.name('Test')
        for template, name in (('Actor', 'ATest'), ('UObject', 'UTest'), ('Struct', 'FTest'),
                               ('Enum', 'ETest'), ('Interface', 'ITest'), ('PlainClass', 'Test'),
                               ('Actor', 'ATest')):
            with self.subTest(template=template):
                self.app.var_template.set(template)
                self.app.refresh_preview()
                self.assertEqual('Test', self.app.var_name.get())
                self.assertEqual(name, self.app.plan.name)
                self.assertIn(name, self.app.views['header'].content)
        self.assertEqual([], self.errors)

    def test_43_full_and_base_name_do_not_trigger_a_second_generation(self):
        self.name('Test'); self.app.on_generate()
        receipt = self.app.last_receipt
        self.name('ATest')
        self.assertEqual('ATest', self.app.plan.name)
        self.assertEqual(self.app.tr('Generated'), self.app.generate_button.cget('text'))
        self.app.on_generate()
        self.assertIs(receipt, self.app.last_receipt)
        self.assertEqual([], self.ask.call_args_list)

    def test_44_add_buttons_visible_and_inside_compact_form(self):
        self.app.update()
        for button in (self.app.target_add_button, self.app.folder_add_button):
            self.assertEqual('+', button.cget('text'))
            self.assertTrue(button.winfo_ismapped())
            self.assertTrue(button.instate(['!disabled']))
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),
                                 self.app.form.winfo_rootx()+self.app.form.winfo_width())
        self.assertEqual(5, len(self.app.inputs))

    def test_45_module_plus_menu_opens_working_module_dialog(self):
        self.app.add_menu.invoke(self.app.tr('Add Module…'))
        d = next(iter(self.app._dialogs))
        self.assertIsInstance(d, ui.ScaffoldDialog)
        self.ask.return_value = True
        d.name.set('ViaPlus'); d.apply()
        self.assertEqual('ViaPlus', self.app.current_target().name)
        self.assertEqual([], self.errors)

    def test_46_module_plus_menu_opens_working_plugin_dialog(self):
        self.app.add_menu.invoke(self.app.tr('Add Plugin…'))
        d = next(iter(self.app._dialogs))
        self.assertTrue(d.plugin)
        self.ask.return_value = True
        d.name.set('PlusPlugin'); d.apply()
        self.assertEqual('PlusPlugin / PlusPlugin', self.app.var_target.get())
        self.assertEqual([], self.errors)

    def test_47_folder_plus_creates_empty_split_folders_and_selects_them(self):
        before = snapshot(self.up.parent)
        self.app.folder_add_button.invoke()
        d = next(iter(self.app._dialogs))
        self.assertIsInstance(d, ui.FolderDialog)
        d.name.set('AI/Movement'); d.apply()
        self.assertEqual('AI/Movement', self.app.var_folder.get())
        self.assertEqual(before, snapshot(self.up.parent))
        for side in ('Public', 'Private'):
            self.assertTrue((self.up.parent / f'Source/Game/{side}/AI/Movement').is_dir())
        self.assertIn('AI/Movement', self.app.inputs['folder']['values'])
        self.assertEqual([], self.errors)

    def test_48_folder_dialog_uses_selected_parent(self):
        self.app.var_folder.set('GameFramework')
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs))
        self.assertEqual('GameFramework', d.parent_folder.get())
        d.name.set('Controller'); d.apply()
        self.assertEqual('GameFramework/Controller', self.app.var_folder.get())
        self.assertTrue((self.up.parent / 'Source/Game/Private/GameFramework/Controller').is_dir())
        self.assertEqual([], self.errors)

    def test_49_folder_cancel_does_not_change_files_or_selection(self):
        before = snapshot(self.up.parent)
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs))
        d.name.set('Cancel/Nested'); d.close()
        self.assertEqual(before, snapshot(self.up.parent))
        self.assertEqual('', self.app.var_folder.get())
        self.assertFalse((self.up.parent / 'Source/Game/Public/Cancel').exists())

    def test_50_invalid_folder_stays_open_and_writes_nothing(self):
        before = snapshot(self.up.parent)
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs))
        for value in ('', '../Escape', '/absolute', 'C:/Escape'):
            d.name.set(value); d.apply()
            self.assertIn(d, self.app._dialogs)
            self.assertEqual(before, snapshot(self.up.parent))
        self.assertEqual(4, len(self.errors))
        d.close()

    def test_51_folder_undo_and_existing_folder_selection(self):
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs)); d.name.set('Created'); d.apply()
        receipt = self.app.last_receipt
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs))
        d.parent_folder.set(''); d.name.set('Created'); d.apply()
        self.assertIs(receipt, self.app.last_receipt)
        self.ask.return_value = True
        self.app.on_undo()
        self.assertFalse((self.up.parent / 'Source/Game/Public/Created').exists())
        self.assertFalse((self.up.parent / 'Source/Game/Private/Created').exists())
        self.assertIsNone(self.app.last_receipt)
        self.assertEqual([], self.errors)

    def test_52_folder_undo_protects_user_content(self):
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs)); d.name.set('Created'); d.apply()
        keep = self.up.parent / 'Source/Game/Private/Created/Keep.txt'
        keep.write_text('my file')
        self.ask.return_value = True
        self.app.on_undo()
        self.assertEqual('my file', keep.read_text())
        self.assertTrue((self.up.parent / 'Source/Game/Public/Created').is_dir())
        self.assertIsNotNone(self.app.last_receipt)
        self.assertEqual(1, len(self.errors))

    def test_53_module_add_preserves_type_raw_name_and_options(self):
        self.app.var_template.set('UObject'); self.name('Test')
        self.app.options['blueprint_type'] = True
        self.ask.return_value = True
        self.app.open_scaffold(False)
        d = next(iter(self.app._dialogs)); d.name.set('Destination'); d.apply()
        self.assertEqual('Test', self.app.var_name.get())
        self.assertEqual('UObject', self.app.var_template.get())
        self.assertTrue(self.app.options['blueprint_type'])
        self.assertEqual('UTest', self.app.plan.name)
        self.assertEqual('Destination', self.app.current_target().name)
        self.assertEqual([], self.errors)

    def test_54_first_module_in_content_only_plugin_is_selectable(self):
        p = self.up.parent / 'Plugins/Vendor/ContentOnly'
        p.mkdir(parents=True)
        descriptor = p / 'ContentOnly.uplugin'
        descriptor.write_text('{"FileVersion":3,"CanContainContent":true}')
        self.app.open_scaffold(False)
        d = next(iter(self.app._dialogs))
        self.assertIn('Vendor/ContentOnly', d.parents)
        d.parent_label.set('Vendor/ContentOnly')
        d.name.set('FirstModule')
        self.ask.return_value = True; d.apply()
        self.assertEqual(descriptor, self.app.current_target().descriptor)
        self.assertEqual('Vendor/ContentOnly / FirstModule', self.app.var_target.get())
        self.assertEqual([], self.errors)
        self.app.open_scaffold(False)
        d = next(iter(self.app._dialogs))
        self.assertEqual('Vendor/ContentOnly', d.parent_label.get())
        d.close()

    def test_55_add_module_is_enabled_even_with_no_existing_modules(self):
        path = self.root / 'Empty'; path.mkdir()
        up = path / 'Empty.uproject'; up.write_text('{"FileVersion":3}')
        self.app.set_project(up)
        self.assertTrue(self.app.target_add_button.instate(['!disabled']))
        self.assertTrue(self.app.folder_add_button.instate(['disabled']))
        self.ask.return_value = True
        self.app.open_scaffold(False)
        d = next(iter(self.app._dialogs)); d.name.set('Empty'); d.apply()
        self.assertEqual('Empty', self.app.current_target().name)
        self.assertTrue((path / 'Source/Empty.Target.cs').exists())
        self.assertTrue(self.app.folder_add_button.instate(['!disabled']))
        self.assertEqual([], self.errors)

    def test_56_add_cancel_confirmation_writes_nothing(self):
        before = snapshot(self.up.parent)
        self.app.open_scaffold(True)
        d = next(iter(self.app._dialogs)); d.name.set('Declined'); d.apply()
        self.assertIn(d, self.app._dialogs)
        self.assertEqual(before, snapshot(self.up.parent))
        self.assertFalse((self.up.parent / 'Plugins/Declined').exists())
        d.close()

    def test_57_folder_dialog_uses_flat_layout(self):
        self.app.var_layout.set('同じフォルダ')
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs)); d.name.set('RootFolder'); d.apply()
        self.assertTrue((self.up.parent / 'Source/Game/RootFolder').is_dir())
        self.assertFalse((self.up.parent / 'Source/Game/Public/RootFolder').exists())
        self.assertIn('RootFolder', self.app.inputs['folder']['values'])
        self.assertEqual([], self.errors)

    def test_58_new_dialogs_respect_modal_and_busy_state(self):
        self.app.open_folder_dialog()
        d = next(iter(self.app._dialogs))
        self.app.open_scaffold(False); self.app.open_folder_dialog()
        self.assertEqual({d}, self.app._dialogs)
        d.close()
        self.app._busy = True; self.app.update_enabled()
        self.app.open_scaffold(True); self.app.open_folder_dialog()
        self.assertFalse(self.app._dialogs)
        self.assertTrue(self.app.target_add_button.instate(['disabled']))
        self.assertTrue(self.app.folder_add_button.instate(['disabled']))
        self.app._busy = False

    def test_59_folder_tool_menu_is_wired_to_same_dialog(self):
        self.app.tools.invoke(self.app.tr('Add Folder…'))
        d = next(iter(self.app._dialogs))
        self.assertIsInstance(d, ui.FolderDialog)
        d.close()

    def test_60_form_actions_fit_above_the_footer(self):
        self.app.update()
        self.assertLessEqual(self.app.advanced_button.winfo_rooty()+self.app.advanced_button.winfo_height(),
                             self.app.actions.winfo_rooty())
        self.assertLessEqual(self.app.tools_button.winfo_rooty()+self.app.tools_button.winfo_height(),
                             self.app.actions.winfo_rooty())

"""Localization coverage, real-widget switching, settings migration and parity."""
from pathlib import Path
import ast
import importlib.machinery
import importlib.util
import json
import os
import re
import string
import tempfile
import unittest
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk

from internal import i18n, model, preferences, ui
from tests.common import fixture, snapshot
from tests import test_ui

ROOT = Path(__file__).resolve().parent.parent
JAPANESE = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')


class MessageTests(unittest.TestCase):
    def test_catalogs_have_identical_keys(self):
        en = json.loads((ROOT / 'internal/locales/en.json').read_text(encoding='utf-8'))
        ja = json.loads((ROOT / 'internal/locales/ja.json').read_text(encoding='utf-8'))
        self.assertEqual(set(en), set(ja))
        self.assertGreater(len(en), 100)
        for key in en:
            self.assertEqual(key, en[key])
            self.assertTrue(ja[key])
            self.assertIsNone(JAPANESE.search(en[key]))

    def test_placeholders_match_and_every_message_renders(self):
        parser = string.Formatter()
        en, ja = i18n.catalog('en'), i18n.catalog('ja')
        for key in en:
            with self.subTest(key=key):
                names = {name for _, name, _, _ in parser.parse(en[key]) if name}
                self.assertEqual(names, {name for _, name, _, _ in parser.parse(ja[key]) if name})
                for lang in ('en', 'ja'):
                    text = i18n.Translator(lang)(key, **{n: 'Example' for n in names})
                    self.assertNotIn('{', text)
                    self.assertNotIn('}', text)

    def test_all_declared_message_keys_exist(self):
        keys = set(i18n.catalog('en'))
        for path in [*ROOT.glob('*.pyw'), *(ROOT / 'internal').glob('*.py')]:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'msg':
                    if node.args and isinstance(node.args[0], ast.Constant):
                        self.assertIn(node.args[0].value, keys, f'{path.name}:{node.lineno}')

    def test_english_is_default_even_with_japanese_os_locale(self):
        with patch.dict(os.environ, {'LANG': 'ja_JP.UTF-8', 'LANGUAGE': 'ja'}):
            self.assertEqual('en', i18n.Translator().language)
            self.assertEqual('Generate', i18n.Translator()('Generate'))

    def test_invalid_languages_fall_back_to_english(self):
        for value in (None, '', 'jp', 'fr', 'ja-JP', 1, False, [], {}):
            self.assertEqual('en', i18n.normalize_language(value))

    def test_messages_are_locale_independent(self):
        value = i18n.msg('Generated {name}.', name='ATest')
        self.assertEqual('Generated ATest.', str(value))
        self.assertEqual('ATest を生成しました。', i18n.Translator('ja').render(value))
        self.assertEqual('Generated ATest.', str(value))

    def test_nested_error_labels_translate(self):
        with self.assertRaises(model.ValidationError) as caught:
            model.type_name('Bad Name', 'Actor')
        error = caught.exception
        self.assertIn('Name must', str(error))
        self.assertIn('名前は英字', i18n.Translator('ja').render(error))
        self.assertEqual('name', error.field)

    def test_nested_transaction_error_translates_at_display_time(self):
        inner = model.ValidationError(i18n.msg('{file} changed during generation.', file='Test.h'))
        outer = model.ValidationError(i18n.msg('Writing was stopped.\n{error}{detail}', error=inner, detail=''))
        self.assertIn('Test.h changed during generation.', str(outer))
        jp = i18n.Translator('ja').render(outer)
        self.assertIn('書き込みを中断しました。', jp)
        self.assertIn('Test.h が生成中に変更されました。', jp)
        self.assertNotIn('Writing', jp)

    def test_user_strings_are_not_translation_keys(self):
        tr = i18n.Translator('ja')
        self.assertEqual('Project', tr.render('Project'))
        self.assertEqual('Project を追加しました。', tr(i18n.msg('Added {name}.', name='Project')))
        self.assertEqual('Project', tr.render(OSError('Project')))
        self.assertEqual('Path/{name}/日本語', tr.render(Path('Path/{name}/日本語')))

    def test_independent_translators(self):
        en, ja = i18n.Translator('en'), i18n.Translator('ja')
        self.assertEqual('Generate', en('Generate'))
        self.assertEqual('生成', ja('Generate'))
        ja.language = 'en'
        self.assertEqual('Generate', ja('Generate'))
        self.assertEqual('Generate', en('Generate'))

    def test_missing_or_damaged_translation_falls_back(self):
        def fake_catalog(language):
            return {'Generated {name}.': 'Broken {unknown}'} if language == 'ja' else {}
        with patch.object(i18n, 'catalog', side_effect=fake_catalog):
            self.assertEqual('Generate', i18n.Translator('ja')('Generate'))
            self.assertEqual('Generated ATest.', i18n.Translator('ja')('Generated {name}.', name='ATest'))

    def test_legacy_layout_values_migrate_to_ids(self):
        for value, expected in (('Public / Private', 'split'), ('同じフォルダ', 'flat'), ('Same Folder', 'flat'),
                                ('Private のみ', 'private'), ('Private Only', 'private'),
                                ('Public のみ', 'public'), ('Public Only', 'public'), ('flat', 'flat')):
            self.assertEqual(expected, model.resolve_layout(value))
        self.assertEqual('', model.resolve_layout('unknown'))

    def test_settings_loader_ignores_wrong_types_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text(json.dumps({'language': 'ja', 'project': 3, 'folder': [], 'layout': 'flat', 'unused': 3}))
            self.assertEqual({'language': 'ja', 'layout': 'flat'}, preferences.read_settings(path))
            for raw in (b'{bad', b'[]', b'null', b'\xff\xfe', b'42'):
                path.write_bytes(raw)
                self.assertEqual({}, preferences.read_settings(path))

    def test_python_310_syntax(self):
        for path in [*ROOT.glob('*.pyw'), *(ROOT / 'internal').glob('*.py')]:
            ast.parse(path.read_text(encoding='utf-8'), feature_version=(3, 10))

    def test_startup_failure_uses_saved_language_and_writes_log(self):
        loader = importlib.machinery.SourceFileLoader('cppgen_startup_test', str(ROOT / 'gui.pyw'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        launcher = importlib.util.module_from_spec(spec)
        loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text('{"language": "ja"}')
            with patch.object(preferences, 'settings_path', return_value=path), patch.object(ui, 'main', side_effect=RuntimeError('test startup failure')), patch.object(launcher, 'fail') as fail:
                launcher.start()
            text = fail.call_args.args[0]
            self.assertIn('起動できませんでした。', text)
            self.assertIn('test startup failure', text)
            self.assertIn('詳細:', text)
            self.assertTrue((path.parent / 'startup-error.log').is_file())


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'GUI display unavailable')
class LocalizationUITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.up = fixture(self.root / 'Project 日本語')
        self.state = self.root / 'state.json'
        self.errors = []
        for name in ('showerror', 'showinfo', 'showwarning'):
            p = patch.object(ui.messagebox, name, side_effect=lambda *args, **kw: self.errors.append(args))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(ui.messagebox, 'askyesno', return_value=True)
        self.ask = p.start(); self.addCleanup(p.stop)
        self.app = ui.App(self.up, self.state)
        self.app.var_target.set('Game')
        self.app.on_target_changed()
        self.app.update()
        self.addCleanup(lambda: self.app.destroy() if self.app.winfo_exists() else None)

    def walk(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self.walk(child)

    def name(self, value='Test'):
        self.app.var_name.set(value)
        self.app.refresh_preview()
        self.app.update()

    def switch(self, language):
        self.app.var_language.set(i18n.LANGUAGES[language])
        self.app.language_box.event_generate('<<ComboboxSelected>>')
        self.app.update()

    def labels(self, parent=None):
        return [str(w.cget('text')) for w in self.walk(parent or self.app) if isinstance(w, (ttk.Label, ttk.Button, ttk.Menubutton, ttk.Checkbutton))]

    def test_default_visible_labels_english(self):
        self.assertEqual('English', self.app.var_language.get())
        self.assertEqual('en', self.app.tr.language)
        labels = self.labels()
        for caption in ('Project', 'Module', 'Type', 'Name', 'Folder', 'Layout', 'Preview', 'Generate', 'Tools', 'Options…'):
            self.assertIn(caption, labels)
        self.assertFalse(JAPANESE.search(' '.join(labels)))
        self.assertEqual(('English', '日本語'), self.app.language_box['values'])

    def test_selector_changes_all_main_captions_without_new_window(self):
        widgets = list(self.walk(self.app))
        geometry = self.app.geometry()
        self.switch('ja')
        self.assertEqual('日本語', self.app.var_language.get())
        self.assertIn('生成', self.labels())
        self.assertIn('プロジェクト', self.labels())
        self.assertIn('プレビュー', self.labels())
        self.assertIn('詳細設定…', self.labels())
        self.assertEqual(geometry, self.app.geometry())
        self.assertEqual(widgets, list(self.walk(self.app)))
        self.assertEqual([], self.errors)

    def test_language_persists_immediately(self):
        self.switch('ja')
        self.assertEqual('ja', json.loads(self.state.read_text())['language'])
        self.app.destroy()
        self.app = ui.App(self.up, self.state)
        self.assertEqual('ja', self.app.tr.language)
        self.assertEqual('生成', self.app.generate_button.cget('text'))
        self.switch('en')
        self.app.destroy()
        self.app = ui.App(self.up, self.state)
        self.assertEqual('en', self.app.tr.language)

    def test_language_can_be_changed_and_saved_without_project(self):
        self.app.destroy()
        with patch.object(model, 'find_project', return_value=None):
            self.app = ui.App(state_path=self.state)
        self.assertIsNone(self.app.project)
        self.assertTrue(self.app.language_box.instate(['readonly']))
        self.switch('ja')
        self.assertEqual({'language':'ja'}, json.loads(self.state.read_text()))
        self.app.destroy()
        with patch.object(model, 'find_project', return_value=None):
            self.app = ui.App(state_path=self.state)
        self.assertEqual('ja', self.app.tr.language)
        self.assertEqual('選択…', self.app.project_button.cget('text'))

    def test_old_settings_default_to_english_and_preserve_layout(self):
        self.app.destroy()
        self.state.write_text(json.dumps({'project': str(self.up), 'target': str(self.up.parent / 'Source/Game'),
                                          'layout': 'Private のみ', 'template': 'Actor', 'folder': 'Game/AI'}))
        self.app = ui.App(state_path=self.state)
        self.assertEqual('en', self.app.tr.language)
        self.assertEqual('private', self.app.current_layout())
        self.assertEqual('Private Only', self.app.var_layout.get())
        self.assertEqual('Game/AI', self.app.var_folder.get())
        self.app.save_settings()
        data = json.loads(self.state.read_text())
        self.assertEqual('private', data['layout'])
        self.assertEqual('en', data['language'])

    def test_switch_preserves_request_preview_selection_scroll_and_inputs(self):
        self.name()
        self.app.var_folder.set('空フォルダ/AI')
        self.app.var_layout.set('Private Only')
        self.app.options['with_tick'] = True
        self.app.options['with_constructor'] = True
        self.app.template_options['PlainClass'] = {'namespace':'Game::AI'}
        self.app.refresh_preview()
        view = self.app.views['cpp']
        view.wrap.set(False); view.toggle_wrap()
        self.app.tabs.select(view)
        self.app.update()
        view.text.tag_add('sel', '1.0', '1.7')
        before = self.app.request()
        plan = self.app.plan
        content = {k:v.content for k,v in self.app.views.items()}
        selected, yview = view.text.tag_ranges('sel'), view.text.yview()
        cache = dict(self.app.template_options)
        disk = snapshot(self.up.parent)
        self.switch('ja')
        self.assertEqual('Private のみ', self.app.var_layout.get())
        self.assertEqual(before, self.app.request())
        self.assertIs(plan, self.app.plan)
        self.assertEqual(content, {k:v.content for k,v in self.app.views.items()})
        self.assertEqual(str(view), self.app.tabs.select())
        self.assertEqual(selected, view.text.tag_ranges('sel'))
        self.assertEqual(yview, view.text.yview())
        self.assertFalse(view.wrap.get())
        self.assertEqual(cache, self.app.template_options)
        self.assertEqual(disk, snapshot(self.up.parent))
        self.assertEqual('Test', self.app.var_name.get())
        self.assertEqual('空フォルダ/AI', self.app.var_folder.get())

    def test_all_four_layouts_round_trip_without_changing_generation(self):
        self.name()
        for caption, code in model.LAYOUTS.items():
            self.app.var_layout.set(caption)
            self.app.refresh_preview()
            original = self.app.request()
            sig = self.app.signature()
            for language in ('ja', 'en', 'ja', 'en'):
                self.switch(language)
                self.assertEqual(code, self.app.current_layout())
                self.assertEqual(original, self.app.request())
                self.assertEqual(sig, self.app.signature())
                self.assertEqual(code, json.loads(self.state.read_text())['layout'])

    def test_generated_state_signature_and_undo_survive_switch(self):
        self.name()
        self.app.on_generate()
        receipt, signature = self.app.last_receipt, self.app.last_signature
        self.assertEqual('Generated', self.app.generate_button.cget('text'))
        self.switch('ja')
        self.assertEqual('生成済み', self.app.generate_button.cget('text'))
        self.assertEqual('ATest を生成しました。', self.app.var_status.get())
        self.assertEqual(signature, self.app.signature())
        self.assertIs(receipt, self.app.last_receipt)
        self.assertTrue(self.app.generate_button.instate(['disabled']))
        with patch.object(model, 'commit') as commit:
            self.app.on_generate()
            commit.assert_not_called()
        self.app.tools.invoke(self.app.tr('Undo Last Action'))
        self.assertFalse((self.up.parent / 'Source/Game/Public/Test.h').exists())
        self.assertEqual('操作を取り消しました。', self.app.var_status.get())

    def test_validation_status_and_tooltip_change_language(self):
        self.name('Bad Name')
        error = self.app._error
        self.assertIn('Name must', self.app._status_full)
        self.switch('ja')
        self.assertIs(error, self.app._error)
        self.assertIn('名前は', self.app._status_full)
        tip = next(t for t in self.app.translations.tooltips if t.widget is self.app.name_entry)
        tip.show(); self.app.update()
        text = str(tip.tip.winfo_children()[0].cget('text'))
        self.assertIn('名前は', text)
        self.switch('en')
        self.assertIsNone(tip.tip)
        tip.show(); self.app.update()
        self.assertIn('Name must', str(tip.tip.winfo_children()[0].cget('text')))
        tip.hide()

    def test_tooltip_help_translates_but_paths_do_not(self):
        self.name()
        tip = next(t for t in self.app.translations.tooltips if t.widget is self.app.name_entry)
        tip.show(); self.app.update()
        self.assertIn('Enter PlayerBase', tip.tip.winfo_children()[0].cget('text'))
        self.switch('ja')
        tip.show(); self.app.update()
        self.assertIn('PlayerBase または APlayerBase', tip.tip.winfo_children()[0].cget('text'))
        tip.hide()
        path_tip = next(t for t in self.app.translations.tooltips if t.widget is self.app.project_entry)
        path_tip.show(); self.app.update()
        self.assertEqual(str(self.up.resolve()), path_tip.tip.winfo_children()[0].cget('text'))
        path_tip.hide()

    def test_add_and_context_menus_translate_and_work(self):
        self.name()
        self.switch('ja')
        self.assertEqual('モジュールを追加…', self.app.add_menu.entrycget(0,'label'))
        self.assertEqual('プラグインを追加…', self.app.add_menu.entrycget(1,'label'))
        view=self.app.views['header']
        self.assertEqual('すべてコピー',view.menu.entrycget(0,'label'))
        self.assertEqual('折り返す',view.menu.entrycget(1,'label'))
        view.menu.invoke(0)
        self.assertEqual(view.content, self.app.clipboard_get())
        self.app.add_menu.invoke(0)
        dialog=next(iter(self.app._dialogs))
        self.assertEqual('モジュールを追加',dialog.title())
        self.assertIn('追加',self.labels(dialog))
        dialog.close()
        self.switch('en')
        self.assertEqual('Add Module…',self.app.add_menu.entrycget(0,'label'))

    def test_options_dialog_retranslates_without_losing_unsaved_edits(self):
        self.app.open_options()
        d=next(iter(self.app._dialogs))
        d.vars['with_tick'].set(True)
        d.vars['extra_includes'].set('MyHeader.h')
        self.assertEqual('Actor Options',d.title())
        self.switch('ja')
        self.assertEqual('Actor の詳細設定',d.title())
        self.assertTrue(d.vars['with_tick'].get())
        self.assertEqual('MyHeader.h',d.vars['extra_includes'].get())
        self.assertIn('コンストラクタ',self.labels(d))
        self.assertIn('適用',self.labels(d))
        self.switch('en')
        self.assertIn('Constructor',self.labels(d))
        d.apply()
        self.assertEqual('MyHeader.h',self.app.options['extra_includes'])
        self.assertEqual([],self.errors)

    def test_scaffold_destination_survives_switch_and_project_name_collision(self):
        path = self.up.parent / 'Plugins/Project/Project.uplugin'
        path.parent.mkdir(parents=True)
        path.write_text('{"FileVersion":3,"Modules":[]}')
        self.app.reload_project()
        self.app.open_scaffold(False)
        d=next(iter(self.app._dialogs))
        self.assertIsNone(d.parents['Project'])
        self.assertEqual(path, d.parents['Project (Plugin)'])
        d.parent_label.set('Project (Plugin)')
        d.name.set('Support')
        self.switch('ja')
        self.assertEqual(path,d.parents[d.parent_label.get()])
        self.assertEqual('Support',d.name.get())
        self.assertIn('プロジェクト',d.parents)
        self.switch('en')
        self.assertEqual('Project (Plugin)',d.parent_label.get())
        d.apply()
        self.assertEqual('Project',self.app.current_target().plugin)
        self.assertEqual('Support',self.app.current_target().name)

    def test_folder_dialog_translates_and_adds_both_folders(self):
        self.switch('ja')
        self.app.open_folder_dialog()
        d=next(iter(self.app._dialogs))
        self.assertEqual('フォルダを追加',d.title())
        self.assertIn('親フォルダ',self.labels(d))
        d.name.set('空/AI')
        self.switch('en')
        self.assertEqual('Add Folder',d.title())
        self.assertIn('Parent Folder',self.labels(d))
        self.assertEqual('空/AI',d.name.get())
        d.apply()
        for side in ('Public','Private'):
            self.assertTrue((self.up.parent/f'Source/Game/{side}/空/AI').is_dir())
        self.assertEqual('Added 空/AI.',self.app.var_status.get())

    def test_confirmation_and_validation_dialogs_follow_language(self):
        self.name()
        self.app.on_generate()
        self.app.options['with_tick']=True
        self.switch('ja')
        self.app.on_generate()
        title,body=self.ask.call_args.args[:2]
        self.assertEqual('既存ファイルの変更',title)
        self.assertIn('変更しますか',body)
        self.assertIn('Test.h',body)
        self.app.open_scaffold(False)
        d=next(iter(self.app._dialogs))
        d.name.set('1Bad')
        d.apply()
        title,body=self.errors[-1]
        self.assertEqual('追加できませんでした',title)
        self.assertIn('名前は',body)
        d.close()

    def test_file_picker_titles_follow_language(self):
        self.switch('ja')
        with patch.object(ui.filedialog,'askopenfilename',return_value='') as choose:
            self.app.browse_project()
        self.assertEqual('プロジェクトを選択',choose.call_args.kwargs['title'])
        self.assertEqual('Unreal Engine プロジェクト',choose.call_args.kwargs['filetypes'][0][0])
        self.switch('en')
        with patch.object(ui.filedialog,'askopenfilename',return_value='') as choose:
            self.app.browse_project()
        self.assertEqual('Select Project',choose.call_args.kwargs['title'])

    def test_pending_worker_messages_use_language_at_display_time(self):
        self.app._busy=True
        self.app.set_status(i18n.msg('Updating project files…'))
        self.app.update_enabled()
        self.switch('ja')
        self.assertEqual('プロジェクトファイルを更新中…',self.app.var_status.get())
        self.app._job_queue.put((True,i18n.msg('Project files updated.')))
        self.app.poll_update()
        self.assertEqual('プロジェクトファイルを更新しました。',self.app.var_status.get())
        self.app._busy=True
        self.app._job_queue.put((False,model.ValidationError(i18n.msg('Project file updates must be run on Windows.'))))
        self.app.poll_update()
        self.assertIn('Windows 上',self.errors[-1][1])

    def test_repeated_switches_do_not_accumulate_widgets_or_callbacks(self):
        self.name()
        widgets = list(self.walk(self.app))
        count = len(self.app.translations.widgets)
        for _ in range(12):
            self.switch('ja'); self.switch('en')
        self.assertEqual(widgets,list(self.walk(self.app)))
        self.assertEqual(count,len(self.app.translations.widgets))
        self.assertEqual([],self.errors)
        self.assertEqual(5,len(self.app.inputs))

    def test_preference_write_failure_does_not_crash_or_change_project(self):
        self.name()
        before=snapshot(self.up.parent)
        with patch.object(ui.os,'replace',side_effect=PermissionError('read-only preference folder')):
            self.switch('ja')
        self.assertEqual('ja',self.app.tr.language)
        self.assertIn('設定を保存できませんでした',self.app._status_full)
        self.assertEqual(before,snapshot(self.up.parent))
        self.assertIsNotNone(self.app.plan)

    def test_unsupported_or_corrupt_saved_language_uses_english(self):
        for raw in ('{"language":"fr"}', '{"language":42}', '{"language":null}', '{bad'):
            self.app.destroy()
            self.state.write_text(raw)
            self.app=ui.App(self.up,self.state)
            self.assertEqual('en',self.app.tr.language)
            self.assertEqual('English',self.app.var_language.get())

    def test_english_and_japanese_controls_fit_compact_window(self):
        for language in ('en','ja'):
            self.switch(language)
            for widget in (self.app.language_box,self.app.project_button,self.app.advanced_button,self.app.tools_button,self.app.generate_button):
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreater(widget.winfo_width(),0)
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.app.winfo_rootx()+self.app.winfo_width())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.app.winfo_rooty()+self.app.winfo_height())
            self.assertLessEqual(self.app.winfo_width(),self.app.px(910))
            self.assertLessEqual(self.app.winfo_height(),self.app.px(520))


class JapaneseUITests(test_ui.UITests):
    """Run every existing GUI regression in Japanese as well as default English."""
    def setUp(self):
        super().setUp()
        self.app.set_language('ja')
        self.app.update()

"""Real-widget checks for filenames, language, logs and legacy preferences."""
from pathlib import Path
import json
import os
import unittest
from unittest.mock import patch

from internal import model, ui
from internal.identity import APP_NAME, LEGACY_APP_NAME
from tests import test_ui


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'GUI display unavailable')
class FilenameUITests(unittest.TestCase):
    # Reuse fixture helpers, without inheriting and re-counting the older tests.
    setUp = test_ui.UITests.setUp
    close_app = test_ui.UITests.close_app
    name = test_ui.UITests.name

    def test_title_preview_and_tabs_use_new_names(self):
        self.name('APlayerBase')
        self.assertEqual(f'{APP_NAME} — Demo', self.app.title())
        self.assertEqual('APlayerBase', self.app.var_name.get())
        self.assertEqual('APlayerBase', self.app.plan.name)
        self.assertEqual('PlayerBase.h', self.app.tabs.tab(self.app.views['header'], 'text'))
        self.assertEqual('PlayerBase.cpp', self.app.tabs.tab(self.app.views['cpp'], 'text'))
        self.assertIn('PlayerBase.generated.h', self.app.views['header'].content)
        self.assertIn('APlayerBase::APlayerBase()', self.app.views['cpp'].content)

    def test_generation_log_uses_type_name_and_actual_filenames_in_both_languages(self):
        self.name('PlayerBase')
        self.app.on_generate(); self.app.update()
        self.assertFalse(self.app.log_open)
        for lang in ('en', 'ja'):
            self.app.set_language(lang)
            self.app.log_view.refresh(); self.app.update()
            text = self.app.log_view.text.get('1.0', 'end-1c')
            self.assertIn('APlayerBase', text)
            self.assertIn('Source/Game/Public/PlayerBase.h', text)
            self.assertIn('Source/Game/Private/PlayerBase.cpp', text)
            self.assertNotIn('APlayerBase.h', text)
            self.assertEqual('PlayerBase', self.app.var_name.get())
        self.app.toggle_log(); self.app.update()
        self.assertTrue(self.app.log_open)
        self.assertTrue(self.app.log_view.winfo_ismapped())
        self.app.toggle_log(); self.app.update()
        self.assertFalse(self.app.log_open)
        self.assertEqual(self.app.px(900), self.app.winfo_width())
        self.assertEqual(self.app.px(510), self.app.winfo_height())

    def test_language_and_type_switch_keep_input_and_unprefixed_filename(self):
        self.name('PlayerBase')
        for lang in ('ja', 'en'):
            self.app.set_language(lang)
            for kind in ('Actor', 'UObject', 'Struct', 'Enum', 'Interface', 'PlainClass'):
                self.app.var_template.set(kind)
                self.app.refresh_preview(); self.app.update()
                self.assertEqual('PlayerBase', self.app.var_name.get())
                self.assertEqual(model.required_prefix(kind) + 'PlayerBase', self.app.plan.name)
                self.assertEqual('PlayerBase.h', self.app.plan.changes[0].path.name)
        self.assertFalse(self.app.log_open)

    def test_prefixed_input_after_generation_does_not_generate_twice(self):
        self.name('PlayerBase'); self.app.on_generate(); self.app.update()
        receipt = self.app.last_receipt
        before = receipt.plan.changes[0].path.read_bytes()
        self.name('APlayerBase'); self.app.on_generate(); self.app.update()
        self.assertIs(receipt, self.app.last_receipt)
        self.assertEqual(before, receipt.plan.changes[0].path.read_bytes())
        self.assertFalse((receipt.plan.changes[0].path.parent / 'APlayerBase.h').exists())
        self.ask.assert_not_called()

    def test_old_prefixed_file_is_explained_in_each_language_without_writes(self):
        old = self.up.parent / 'Source/Game/Public/APlayerBase.h'
        old.write_text('// keep this file\n')
        self.name('APlayerBase')
        self.assertIsNone(self.app.plan)
        self.assertTrue(self.app.generate_button.instate(['disabled']))
        self.assertIn('prefixed file', self.app._status_full)
        self.app.set_language('ja'); self.app.update()
        self.assertIn('接頭辞付きファイル', self.app._status_full)
        self.assertEqual('// keep this file\n', old.read_text())
        self.assertFalse((old.parent / 'PlayerBase.h').exists())

    def test_legacy_preferences_save_to_new_name_and_survive_relaunch(self):
        self.close_app()
        base = self.root / 'UserSettings'
        old = base / LEGACY_APP_NAME / 'compact-ui.json'
        old.parent.mkdir(parents=True)
        content = json.dumps({'language': 'ja', 'project': str(self.up), 'template': 'Struct', 'layout': 'split'})
        old.write_text(content, encoding='utf-8')
        with patch.dict(os.environ, {'APPDATA': str(base), 'XDG_CONFIG_HOME': str(base)}):
            self.app = ui.App(); self.app.update()
            self.assertEqual('ja', self.app.tr.language)
            self.assertEqual('Struct', self.app.var_template.get())
            self.assertEqual(f'{APP_NAME} — Demo', self.app.title())
            new = base / APP_NAME / 'compact-ui.json'
            self.assertEqual(new, self.app.state_path)
            self.app.set_language('en'); self.app.save_settings()
            self.close_app()
            self.assertEqual(content, old.read_text())
            self.assertEqual('en', json.loads(new.read_text())['language'])
            self.app = ui.App(); self.app.update()
            self.assertEqual('en', self.app.tr.language)
            self.assertFalse(self.app.log_open)

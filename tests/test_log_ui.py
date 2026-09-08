from pathlib import Path
from threading import get_ident
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import tkinter as tk

from internal import ui, model, platform_tools
from internal.activity import format_entry
from internal.i18n import msg
from tests.common import fixture, snapshot


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'GUI display unavailable')
class LogUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.up=fixture(self.root/'Project 日本語')
        self.state=self.root/'settings.json'
        self.errors=[]
        for name in ('showerror','showinfo','showwarning'):
            p=patch.object(ui.messagebox,name,side_effect=lambda *a,**k:self.errors.append(a))
            p.start(); self.addCleanup(p.stop)
        p=patch.object(ui.messagebox,'askyesno',return_value=False)
        self.ask=p.start(); self.addCleanup(p.stop)
        self.app=ui.App(self.up,self.state)
        self.app.var_target.set('Game'); self.app.on_target_changed(); self.app.update()
        self.addCleanup(self.close)

    def close(self):
        try:
            if self.app.winfo_exists(): self.app.destroy()
        except tk.TclError: pass

    def records(self):
        return self.app.activity.snapshot()[1]

    def text(self):
        return ''.join(format_entry(e,self.app.tr) for e in self.records())

    def rendered(self):
        self.app.log_view.refresh()
        return self.app.log_view.text.get('1.0','end-1c')

    def name(self, name='Test'):
        self.app.var_name.set(name); self.app.refresh_preview(); self.app.update()

    def pump(self, predicate, seconds=4):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            self.app.update(); time.sleep(.01)
        self.app.update()
        self.assertTrue(predicate())

    def command(self,code):
        return [sys.executable,'-S','-u','-c',code]

    def test_01_closed_by_default_without_increasing_window(self):
        self.assertFalse(self.app.log_open)
        self.assertFalse(self.app.log_view.winfo_ismapped())
        self.assertFalse(self.app.log_copy.winfo_ismapped())
        self.assertTrue(self.app.log_toggle.winfo_ismapped())
        self.assertEqual('▸ Log',self.app.log_toggle.cget('text'))
        self.assertEqual((self.app.px(900),self.app.px(510)),(self.app.winfo_width(),self.app.winfo_height()))

    def test_02_expand_and_collapse_preserve_input_preview_and_geometry(self):
        self.name(); self.app.tabs.select(self.app.views['cpp'])
        old=(self.app.geometry(),self.app.plan,self.app.last_receipt)
        self.app.log_toggle.invoke(); self.app.update()
        self.assertTrue(self.app.log_view.winfo_ismapped())
        self.assertTrue(self.app.log_copy.winfo_ismapped())
        self.assertGreater(self.app.winfo_height(),self.app.px(510))
        self.assertEqual('Test',self.app.var_name.get())
        self.assertEqual(str(self.app.views['cpp']),self.app.tabs.select())
        self.app.log_toggle.invoke(); self.app.update()
        self.assertEqual(old,(self.app.geometry(),self.app.plan,self.app.last_receipt))

    def test_03_restart_is_closed_even_when_previously_open(self):
        self.app.toggle_log(); self.app.set_language('ja'); self.app.on_close()
        self.app=ui.App(self.up,self.state); self.app.update()
        self.assertFalse(self.app.log_open)
        self.assertEqual('ja',self.app.tr.language)
        self.assertEqual('▸ ログ',self.app.log_toggle.cget('text'))
        self.assertNotIn('log_open',json.loads(self.state.read_text()))
        self.assertFalse(self.records())

    def test_04_source_logs_record_while_closed(self):
        self.name(); self.app.on_generate()
        text=self.text()
        self.assertIn('Generating ATest (Actor)',text)
        self.assertIn('Created: Source/Game/Public/ATest.h',text)
        self.assertIn('Created: Source/Game/Private/ATest.cpp',text)
        self.assertIn('Generated ATest: 2 file(s)',text)
        self.assertFalse(self.app.log_open)
        self.app.toggle_log()
        self.assertEqual(text,self.rendered())
        self.assertTrue((self.up.parent/'Source/Game/Public/ATest.h').exists())

    def test_05_typing_and_preview_do_not_spam_history(self):
        for value in ('T','Te','Test','Bad Name','Test'):
            self.name(value)
        self.app.set_language('ja')
        self.assertFalse(self.records())

    def test_06_copy_and_clear_do_not_change_files_or_undo(self):
        self.name(); self.app.on_generate(); self.app.toggle_log()
        receipt=self.app.last_receipt; before=snapshot(self.up.parent)
        self.app.log_copy.invoke()
        self.assertEqual(self.text(),self.app.clipboard_get())
        self.app.log_clear.invoke()
        self.assertFalse(self.records())
        self.assertEqual('',self.rendered())
        self.assertEqual(before,snapshot(self.up.parent))
        self.assertIs(receipt,self.app.last_receipt)

    def test_07_log_messages_retranslate_engine_output_stays_raw(self):
        self.name(); self.app.on_generate()
        self.app.log('Project files updated.',source='UE')
        self.app.toggle_log(); count=len(self.records())
        old=self.app.geometry()
        self.app.set_language('ja')
        text=self.rendered()
        self.assertIn('[成功] [ソース]',text)
        self.assertIn('作成: Source/Game/Public/ATest.h',text)
        self.assertIn('Project files updated.',text)
        self.assertIn('▾ ログ',self.app.log_toggle.cget('text'))
        self.assertEqual(old,self.app.geometry())
        self.assertEqual(count,len(self.records()))

    def test_08_log_readonly_and_select_all(self):
        self.app.log('read-only message'); self.app.toggle_log()
        self.assertEqual('disabled',self.app.log_view.text.cget('state'))
        before=self.rendered()
        self.app.log_view.text.insert('end','must not appear')
        self.assertEqual(before,self.rendered())
        self.app.log_view.select_all()
        self.assertTrue(self.app.log_view.text.tag_ranges('sel'))

    def test_09_scroll_up_is_not_forced_to_latest(self):
        self.app.toggle_log()
        for i in range(100): self.app.log(f'first-{i}')
        self.rendered(); self.app.update()
        self.assertGreater(self.app.log_view.text.yview()[1],.99)
        self.app.log_view.text.yview_moveto(0); self.app.update()
        self.app.log('new-last'); self.rendered(); self.app.update()
        self.assertLess(self.app.log_view.text.yview()[0],.05)
        self.app.log_view.text.see('end'); self.app.update()
        self.app.log('newest'); self.rendered(); self.app.update()
        self.assertGreater(self.app.log_view.text.yview()[1],.99)

    def test_10_rendered_history_trims_and_clear_new_output_is_not_duplicated(self):
        self.app.activity.max_entries=8
        self.app.toggle_log()
        for i in range(20):
            self.app.log(f'record-{i:02}'); self.rendered()
        text=self.rendered()
        self.assertNotIn('record-11',text)
        self.assertEqual(8,len(text.splitlines()))
        self.assertEqual(self.text(),text)
        self.app.activity.clear(); self.app.log('after-clear')
        self.assertEqual(self.text(),self.rendered())
        self.assertEqual(1,self.rendered().count('after-clear'))

    def test_11_large_hidden_log_does_not_render_until_opened(self):
        for i in range(6500): self.app.log(f'output-{i}')
        self.app.update()
        self.assertEqual('',self.app.log_view.text.get('1.0','end-1c'))
        self.assertEqual(5000,len(self.records()))
        self.app.toggle_log(); self.app.update()
        self.assertIn('output-6499',self.rendered())
        self.assertEqual(5000,len(self.rendered().splitlines()))

    def test_12_live_process_output_arrives_while_busy(self):
        main_thread=get_ident()
        self.app.toggle_log()
        command=self.command('import sys,time; print("early-stdout"); print("warning: early-stderr",file=sys.stderr); time.sleep(.6); print("late-output")')
        with patch.object(platform_tools,'project_command',return_value=command):
            self.app.run_update()
            self.pump(lambda:'early-stdout\n' in self.app.log_view.text.get('1.0','end-1c'))
            self.assertTrue(self.app._busy)
            self.assertIn('early-stderr',self.text())
            self.assertEqual(main_thread,get_ident())
            self.app.set_language('ja')
            self.app.toggle_log(); self.app.toggle_log()
            self.pump(lambda:not self.app._busy)
        self.assertIn('late-output',self.rendered())
        self.assertIn('終了コード: 0',self.rendered())
        self.assertIn('プロジェクトファイルを更新しました',self.rendered())
        self.assertEqual([],self.errors)

    def test_13_update_failure_keeps_full_output_and_does_not_auto_open(self):
        code='import sys; [print("diagnostic-%d"%i) for i in range(150)]; print("error: engine-failure",file=sys.stderr); sys.exit(4)'
        with patch.object(platform_tools,'project_command',return_value=self.command(code)):
            self.app.run_update(); self.pump(lambda:not self.app._busy)
        text=self.text()
        self.assertIn('diagnostic-0\n',text)
        self.assertIn('diagnostic-149',text)
        self.assertIn('Exit code: 4',text)
        self.assertIn('engine-failure',text)
        self.assertFalse(self.app.log_open)
        self.assertTrue(self.errors)

    def test_14_timeout_is_logged_and_gui_becomes_available(self):
        original=platform_tools.update_project
        def short(project,on_log=None,cancel=None):
            return original(project,on_log=on_log,cancel=cancel,timeout=.25)
        with patch.object(platform_tools,'project_command',return_value=self.command('import time; print("before-timeout"); time.sleep(20)')), patch.object(platform_tools,'update_project',side_effect=short):
            self.app.run_update(); self.pump(lambda:not self.app._busy)
        self.assertIn('before-timeout',self.text())
        self.assertIn('timed out',self.text())
        self.assertTrue(self.app.project_button.instate(['!disabled']))

    def test_15_engine_resolution_error_is_logged(self):
        with patch.object(platform_tools,'project_command',side_effect=model.ValidationError(msg('The Unreal Engine installation for this project was not found.'))):
            self.app.run_update(); self.pump(lambda:not self.app._busy)
        self.assertIn('installation for this project was not found',self.text())
        self.assertEqual('error',self.records()[-1].level)

    def test_16_write_failure_is_logged(self):
        self.name()
        with patch.object(model,'commit',side_effect=PermissionError('test read-only destination')):
            self.app.on_generate()
        self.assertIn('Generation failed.',self.text())
        self.assertIn('read-only destination',self.text())
        self.assertFalse(self.app.log_open)

    def test_17_module_plugin_and_folder_actions_logged(self):
        self.ask.return_value=True
        self.app.open_scaffold(False)
        d=next(iter(self.app._dialogs)); d.name.set('NewModule'); d.apply()
        self.assertIn('[Module]',self.text())
        self.assertIn('Created: Source/NewModule/NewModule.Build.cs',self.text())
        self.assertIn('Updated: Demo.uproject',self.text())
        self.app.open_scaffold(True)
        d=next(iter(self.app._dialogs)); d.name.set('NewPlugin'); d.apply()
        self.assertIn('[Plugin]',self.text())
        self.assertIn('NewPlugin.uplugin',self.text())
        self.app.open_folder_dialog()
        d=next(iter(self.app._dialogs)); d.name.set('AI/Movement'); d.apply()
        self.assertIn('[Folder]',self.text())
        self.assertIn('Public/AI/Movement',self.text())
        self.assertIn('Private/AI/Movement',self.text())
        self.assertEqual([],self.errors)

    def test_18_backups_and_undo_are_logged(self):
        self.name(); self.app.on_generate()
        self.ask.return_value=True
        self.app.options['with_tick']=True; self.app.on_generate()
        self.assertIn('Backup:',self.text())
        self.assertIn('Updated: Source/Game/Public/ATest.h',self.text())
        self.app.on_undo()
        self.assertIn('Restored: Source/Game/Public/ATest.h',self.text())
        self.assertIn('Action undone.',self.text())
        self.assertNotIn('virtual void Tick', (self.up.parent/'Source/Game/Public/ATest.h').read_text())

    def test_19_cancelled_overwrite_does_not_claim_success(self):
        self.name(); self.app.on_generate(); self.app.activity.clear()
        self.app.options['with_tick']=True
        self.app.on_generate()
        self.assertIn('Generation cancelled',self.text())
        self.assertNotIn('[Success]',self.text())
        self.assertNotIn('virtual void Tick',(self.up.parent/'Source/Game/Public/ATest.h').read_text())

    def test_20_clear_during_update_allows_future_lines(self):
        with patch.object(platform_tools,'project_command',return_value=self.command('import time; print("erase-me"); time.sleep(.5); print("keep-me")')):
            self.app.run_update()
            self.pump(lambda:any(e.message=='erase-me' for e in self.records()))
            self.app.log_view.clear()
            self.pump(lambda:not self.app._busy)
        self.assertNotIn('erase-me',self.text())
        self.assertIn('keep-me',self.text())

    def test_21_destroy_cancels_worker_without_tk_calls(self):
        with patch.object(platform_tools,'project_command',return_value=self.command('import time; print("ready"); time.sleep(20)')):
            self.app.run_update()
            self.pump(lambda:any(e.message=='ready' for e in self.records()))
            worker=self.app._worker
            self.app.destroy()
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
        self.assertTrue(self.app._update_cancel.is_set())
        self.assertIsNone(self.app._log_timer)
        self.assertIsNone(self.app._job_timer)

    def test_22_error_and_warning_have_text_and_color_tags(self):
        self.app.log('test warning','warning','UE'); self.app.log('test error','error','UE')
        self.app.toggle_log(); self.rendered()
        self.assertIn('[Warning]',self.rendered())
        self.assertIn('[Error]',self.rendered())
        self.assertTrue(self.app.log_view.text.tag_ranges('error'))
        self.assertTrue(self.app.log_view.text.tag_ranges('warning'))

    def test_23_append_logs_are_distinct_from_replace(self):
        self.name(); self.app.on_generate(); self.app.activity.clear()
        self.ask.return_value=True
        self.app.var_template.set('Struct'); self.app.options['append_to']='ATest.h'; self.name('Data')
        self.app.on_generate()
        self.assertIn('Appended: Source/Game/Public/ATest.h',self.text())
        self.assertIn('FData',(self.up.parent/'Source/Game/Public/ATest.h').read_text())

    def test_24_no_duplicate_generation_logs(self):
        self.name(); self.app.on_generate()
        count=len(self.records())
        self.app.on_generate()
        self.assertEqual(count,len(self.records()))

    def test_25_log_controls_fit_with_status_in_both_languages(self):
        self.name(); self.app.on_generate(); self.app.toggle_log()
        for language in ('en','ja'):
            self.app.set_language(language); self.app.update()
            for widget in (self.app.log_toggle,self.app.log_copy,self.app.log_clear,self.app.generate_button):
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.app.winfo_rootx()+self.app.winfo_width())
            self.assertLess(self.app.advanced_button.winfo_rooty()+self.app.advanced_button.winfo_height(),self.app.actions.winfo_rooty())

    def test_26_source_to_auto_update_keeps_chronological_history(self):
        self.name(); self.app.auto_update=True
        with patch.object(platform_tools,'project_command',return_value=self.command('print("engine-output")')):
            self.app.on_generate(); self.pump(lambda:not self.app._busy)
        text=self.text()
        self.assertLess(text.index('Generated ATest:'),text.index('Updating project files…'))
        self.assertLess(text.index('Updating project files…'),text.index('Exit code:'))
        self.assertIsNotNone(self.app.last_receipt)

    def test_27_maximized_log_toggle_does_not_overwrite_restore_geometry(self):
        geometry = self.app.geometry
        with patch.object(self.app, 'state', return_value='zoomed'), patch.object(self.app, 'geometry', wraps=geometry) as resize:
            self.app.toggle_log(); self.app.update()
            self.assertTrue(self.app.log_open)
            self.app.toggle_log(); self.app.update()
        resize.assert_not_called()

    def test_28_long_status_cannot_push_generate_off_compact_window(self):
        self.app.geometry(f'{self.app.px(780)}x{self.app.px(510)}')
        self.app.toggle_log()
        for language in ('en', 'ja'):
            self.app.set_language(language)
            self.app.set_status(msg('Generated {name}.', name='A' + 'LongName' * 12))
            self.app.update()
            label, button = self.app.status_label, self.app.generate_button
            self.assertLessEqual(label.winfo_rootx()+label.winfo_width(), button.winfo_rootx())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), self.app.winfo_rootx()+self.app.winfo_width())

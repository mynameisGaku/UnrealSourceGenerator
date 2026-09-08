from pathlib import Path
from threading import Event
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from internal import model, platform_tools
from internal.process_output import OutputLines, stream_process, _stop_process
from tests.common import fixture


class OutputLineTests(unittest.TestCase):
    def decode(self, chunks, encodings=('utf-8', 'cp932')):
        lines = []
        decoder = OutputLines(lines.append, encodings)
        for chunk in chunks: decoder.feed(chunk)
        decoder.finish()
        return lines

    def test_utf8_japanese_split_at_every_byte(self):
        raw = '生成中… 日本語🙂\nComplete\n'.encode()
        self.assertEqual(['生成中… 日本語🙂', 'Complete'], self.decode([bytes([b]) for b in raw]))

    def test_cp932_and_utf8_mixed_lines(self):
        self.assertEqual(['プロジェクト生成', '日本語🙂'], self.decode([
            'プロジェクト生成\r\n'.encode('cp932'), '日本語🙂\n'.encode()]))

    def test_progress_cr_and_crlf_split(self):
        self.assertEqual(['10%', '20%', '30%', 'done'], self.decode([b'10%\r20%\r', b'\n30%\r', b'done']))

    def test_no_final_newline(self):
        self.assertEqual(['first', 'final line'], self.decode([b'first\nfinal', b' line']))

    def test_invalid_bytes_replace_instead_of_crash(self):
        text = '\n'.join(self.decode([b'A\x81\n'], ('utf-8',)))
        self.assertIn('A', text)
        self.assertIn('\ufffd', text)

    def test_ansi_color_and_bom_removed(self):
        self.assertEqual(['error: broken', 'path'], self.decode([b'\xef\xbb\xbf\x1b[31', b'merror: broken\x1b[0m\npath\0\n']))

    def test_huge_unterminated_line_remains_bounded(self):
        output=[]
        decoder=OutputLines(output.append)
        raw = ('a' * 16383 + '日本語🙂') * 20
        decoder.feed(raw.encode())
        self.assertLessEqual(len(decoder.pending), decoder.LIMIT)
        decoder.finish()
        self.assertEqual(raw, ''.join(output))

    def test_huge_cp932_line_keeps_character_boundary(self):
        raw = ('x' * 16383 + '日本語') * 3
        self.assertEqual(raw, ''.join(self.decode([raw.encode('cp932')])))


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)

    def run_code(self, code, **kwargs):
        lines = []
        result = stream_process([sys.executable, '-S', '-u', '-c', code], self.cwd, lines.append, **kwargs)
        return result, lines

    def test_stdout_and_stderr_merged(self):
        result, lines = self.run_code('import sys; print("stdout"); print("stderr", file=sys.stderr); print("last")')
        self.assertEqual(0, result.returncode)
        self.assertEqual(['stdout', 'stderr', 'last'], lines)

    def test_output_is_delivered_before_process_finishes(self):
        moments = []
        start = time.monotonic()
        result = stream_process([sys.executable, '-S', '-u', '-c', 'import time; print("early"); time.sleep(.45); print("late")'],
                                self.cwd, lambda line: moments.append((line, time.monotonic()-start)))
        self.assertEqual(['early', 'late'], [line for line, _ in moments])
        self.assertGreater(moments[1][1]-moments[0][1], .3)
        self.assertEqual(0, result.returncode)

    def test_nonzero_exit_and_tail(self):
        result, lines = self.run_code('import sys; print("failure"); sys.exit(7)')
        self.assertEqual(7, result.returncode)
        self.assertIn('failure', result.tail)

    def test_stdin_is_eof_not_interactive(self):
        result, lines = self.run_code('import sys; print(repr(sys.stdin.read()))')
        self.assertEqual(["''"], lines)
        self.assertEqual(0, result.returncode)

    def test_timeout_terminates_and_preserves_output(self):
        start = time.monotonic()
        result, lines = self.run_code('import time; print("before timeout"); time.sleep(20)', timeout=.25)
        self.assertEqual('timeout', result.stopped)
        self.assertLess(time.monotonic()-start, 3)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('before timeout', result.tail)

    def test_silent_timeout(self):
        result, lines = self.run_code('import time; time.sleep(20)', timeout=.15)
        self.assertEqual('timeout', result.stopped)
        self.assertEqual([], lines)

    def test_cancellation_during_output(self):
        cancel = Event()
        result = stream_process([sys.executable, '-S', '-u', '-c', 'import time; print("cancel now"); time.sleep(20)'],
                                self.cwd, lambda line: cancel.set(), cancel=cancel)
        self.assertEqual('cancelled', result.stopped)
        self.assertNotEqual(0, result.returncode)

    def test_precancel_does_not_launch(self):
        cancel = Event(); cancel.set()
        with patch('internal.process_output.subprocess.Popen') as launch:
            result = stream_process(['not-an-app'], self.cwd, lambda _: None, cancel=cancel)
        launch.assert_not_called()
        self.assertEqual('cancelled', result.stopped)

    def test_pipe_flood_does_not_deadlock_or_lose_lines(self):
        result, lines = self.run_code('import sys; [sys.stderr.write("line-%d\\n" % i) for i in range(12000)]', timeout=10)
        self.assertEqual(0, result.returncode)
        self.assertEqual(12000, len(lines))
        self.assertEqual('line-11999', lines[-1])
        self.assertLessEqual(len(result.tail), 3500)

    def test_pipe_closed_early_still_waits_for_exit(self):
        result, lines = self.run_code('import os,time; os.close(1); os.close(2); time.sleep(.2)')
        self.assertGreaterEqual(result.seconds, .2)
        self.assertEqual(0, result.returncode)
        self.assertFalse(lines)

    def test_observer_exception_reaps_child(self):
        pids = []
        def observer(line):
            pids.append(int(line))
            raise RuntimeError('observer failure')
        with self.assertRaisesRegex(RuntimeError, 'observer failure'):
            stream_process([sys.executable, '-S', '-u', '-c', 'import os,time; print(os.getpid()); time.sleep(10)'], self.cwd, observer)
        if os.name != 'nt':
            with self.assertRaises(ProcessLookupError): os.kill(pids[0], 0)

    def test_missing_executable_raises(self):
        with self.assertRaises(OSError):
            stream_process([str(self.cwd/'missing-application')], self.cwd, lambda _: None)

    def test_windows_stop_uses_tree_and_no_console(self):
        fake = MagicMock(pid=4321)
        fake.poll.side_effect = [None, None]
        with patch('internal.process_output.sys.platform', 'win32'), patch('internal.process_output.subprocess.run') as run:
            _stop_process(fake)
        self.assertEqual(['/PID', '4321', '/T', '/F'], run.call_args.args[0][1:])
        self.assertEqual(subprocess.DEVNULL, run.call_args.kwargs['stdout'])
        self.assertIn('creationflags', run.call_args.kwargs)
        fake.kill.assert_called_once()

    def test_timeout_invalid_value(self):
        with self.assertRaises(ValueError): self.run_code('pass', timeout=0)


class UpdateLogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project=model.load_project(fixture(Path(self.temp.name)))

    def update(self, code, **kwargs):
        events=[]
        with patch.object(platform_tools,'project_command',return_value=[sys.executable,'-S','-u','-c',code]):
            result=platform_tools.update_project(self.project,on_log=lambda message,level: events.append((str(message),level)),**kwargs)
        return str(result),events

    def test_command_project_exit_and_output(self):
        result, events=self.update('print("warning: test warning")')
        self.assertEqual('Project files updated.', result)
        self.assertTrue(any('Command:' in text for text,level in events))
        self.assertTrue(any('Project:' in text for text,level in events))
        self.assertIn(('warning: test warning','warning'),events)
        self.assertTrue(any('Exit code: 0' in text and level=='success' for text,level in events))

    def test_timeout_is_localizable_error(self):
        with self.assertRaisesRegex(model.ValidationError,'timed out'):
            self.update('import time; print("last output"); time.sleep(20)',timeout=.2)

    def test_observer_failure_does_not_interrupt_update(self):
        with patch.object(platform_tools,'project_command',return_value=[sys.executable,'-S','-c','print("ok")']):
            result=platform_tools.update_project(self.project,on_log=lambda *a: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual('Project files updated.', str(result))

    def test_return_code_not_keyword_decides_success(self):
        result,events=self.update('print("failed attempts: 0")')
        self.assertEqual('Project files updated.', result)
        with self.assertRaisesRegex(model.ValidationError,'exit code 9'):
            self.update('import sys; print("no diagnostic"); sys.exit(9)')

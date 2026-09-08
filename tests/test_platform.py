from pathlib import Path
from types import SimpleNamespace
import ast
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from internal import launch, platform_tools, model
from tests.common import fixture


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = model.load_project(fixture(Path(self.temp.name)))

    def test_01_update_does_not_guess_another_engine(self):
        if sys.platform == 'win32':
            self.skipTest('Non-Windows branch')
        with self.assertRaises(model.ValidationError):
            platform_tools.project_command(self.project)

    def test_02_update_waits_and_captures_output(self):
        command = [sys.executable, '-S', '-c', 'print("live output")']
        events = []
        popen = subprocess.Popen
        with patch.object(platform_tools, 'project_command', return_value=command), \
             patch('internal.process_output.subprocess.Popen', wraps=popen) as run:
            self.assertEqual('Project files updated.', str(platform_tools.update_project(
                self.project, on_log=lambda text, level: events.append((str(text), level)))))
            self.assertEqual(command, run.call_args.args[0])
            self.assertEqual(subprocess.DEVNULL, run.call_args.kwargs['stdin'])
            self.assertEqual(subprocess.PIPE, run.call_args.kwargs['stdout'])
            self.assertEqual(subprocess.STDOUT, run.call_args.kwargs['stderr'])
            self.assertNotIn('shell', run.call_args.kwargs)
        self.assertTrue(any(text == 'live output' for text, _ in events))
        self.assertTrue(any('Exit code: 0' in text for text, _ in events))

    def test_03_update_error_is_reported(self):
        command = [sys.executable, '-S', '-c', 'import sys; print("BUILD FAILED"); sys.exit(3)']
        with patch.object(platform_tools, 'project_command', return_value=command):
            with self.assertRaisesRegex(model.ValidationError, 'BUILD FAILED'):
                platform_tools.update_project(self.project)

    def test_04_windowless_launcher_no_cli_arguments(self):
        with patch.object(launch.subprocess, 'Popen') as process:
            self.assertEqual(0, launch.main())
            args = process.call_args.args[0]
            self.assertEqual('gui.pyw', Path(args[-1]).name)
            self.assertEqual(2, len(args))
            self.assertNotIn('shell', process.call_args.kwargs)
            self.assertEqual(subprocess.DEVNULL, process.call_args.kwargs['stdin'])

    def test_05_windows_launcher_crlf(self):
        root = Path(launch.__file__).resolve().parent.parent
        data = (root / 'gui.bat').read_bytes()
        self.assertEqual(data.count(b'\n'), data.count(b'\r\n'))
        self.assertNotIn(b'--module', data)
        self.assertNotIn(b'pause', data.lower())

    def test_06_source_syntax(self):
        root = Path(launch.__file__).resolve().parent.parent
        for p in list((root / 'internal').glob('*.py')) + [root / 'gui.pyw']:
            with self.subTest(file=p.name):
                ast.parse(p.read_text(encoding='utf-8'), feature_version=(3, 10))

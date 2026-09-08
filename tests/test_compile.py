"""Compile the non-reflected templates with a small CoreMinimal stub, not UE/UHT."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from internal import model
from tests.common import fixture


@unittest.skipUnless(shutil.which('g++') or shutil.which('clang++'), 'C++ compiler unavailable')
class CompileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = model.load_project(fixture(self.root))
        self.target = next(t for t in self.project.targets if t.name == 'Game')
        self.public = self.target.folder / 'Public'
        self.private = self.target.folder / 'Private'
        (self.public / 'CoreMinimal.h').write_text('#pragma once\n#include <string>\nusing int32 = int;\nusing uint8 = unsigned char;\nusing FString = std::string;\n')
        (self.public / 'Extra.h').write_text('#pragma once\nstruct FOutside { int Value = 0; };\n')

    def emit(self, template, name, **options):
        req = model.Request(self.target, template, name, options={'with_api':False, **options})
        plan = model.build_plan(self.project, req)
        model.commit(plan, allow_existing=True)

    def compile(self, main):
        source = self.root / 'main.cpp'; source.write_text(main, encoding='utf-8')
        exe = self.root / 'compiled'
        compiler = shutil.which('g++') or shutil.which('clang++')
        command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-pedantic', '-I', str(self.public),
                   str(source), *map(str, self.private.glob('*.cpp')), '-o', str(exe)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        run = subprocess.run([str(exe)], capture_output=True, timeout=5)
        self.assertEqual(0, run.returncode)

    def test_01_split_inline_struct_enum_namespace_compile_and_execute(self):
        self.emit('PlainClass', 'Split', namespace='Tools', extra_includes='Extra.h')
        self.emit('PlainClass', 'Inline', header_only=True, namespace='Tools')
        self.emit('PlainStruct', 'Data', namespace='Tools')
        self.emit('PlainEnum', 'Mode', namespace='Tools')
        self.compile('''#include "Split.h"
#include "Inline.h"
#include "FData.h"
#include "EMode.h"
#include "EMode.h"
int main() { Tools::Split A; Tools::Inline B; Tools::FData D; FOutside E;
    return D.Value + E.Value + static_cast<int>(Tools::EMode::None); }
''')

    def test_02_append_class_enum_namespace_include_guard_compile_and_execute(self):
        self.emit('PlainClass', 'Shared')
        self.emit('PlainClass', 'Extra', namespace='Tools', extra_includes='Extra.h', append_to='Shared.h')
        self.emit('PlainEnum', 'Mode', namespace='Tools', append_to='Shared.h')
        self.compile('''#include "Shared.h"
#include "Shared.h"
int main() { Shared A; Tools::Extra B; FOutside C;
    return C.Value + static_cast<int>(Tools::EMode::None); }
''')

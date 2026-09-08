from pathlib import Path
from threading import Thread
import unittest
from internal.activity import ActivityLog, format_entry
from internal.i18n import Translator, msg
from internal.model import ValidationError


class ActivityTests(unittest.TestCase):
    def test_empty_and_clear(self):
        log = ActivityLog()
        self.assertEqual((0, ()), log.snapshot())
        log.add('one'); log.clear()
        revision, entries = log.snapshot()
        self.assertEqual(2, revision)
        self.assertFalse(entries)
        log.add('two')
        self.assertEqual(2, log.snapshot()[1][0].sequence)

    def test_entry_limit_retains_newest(self):
        log = ActivityLog(max_entries=3)
        for i in range(10): log.add(str(i))
        self.assertEqual(['7', '8', '9'], [e.message for e in log.snapshot()[1]])
        self.assertEqual(7, log.dropped)

    def test_character_budget_and_oversized_record(self):
        log = ActivityLog(max_chars=20)
        log.add('A' * 15); log.add('B' * 15)
        self.assertEqual(['B' * 15], [e.message for e in log.snapshot()[1]])
        log.add('C' * 50)
        self.assertEqual('C' * 20, log.snapshot()[1][0].message)

    def test_multiple_producers_have_unique_ordered_sequences(self):
        log = ActivityLog(max_entries=2000)
        threads = [Thread(target=lambda: [log.add('message') for _ in range(250)]) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(list(range(1, 1001)), [e.sequence for e in log.snapshot()[1]])

    def test_structured_messages_retranslate_but_engine_text_does_not(self):
        log = ActivityLog()
        log.add(msg('Created: {path}', path='Source/日本語/ATest.h'), 'success', msg('Source'))
        entry = log.snapshot()[1][0]
        self.assertIn('[Success] [Source] Created:', format_entry(entry, Translator('en')))
        self.assertIn('[成功] [ソース] 作成:', format_entry(entry, Translator('ja')))
        log.add('Project files updated.', 'info', 'UE')
        self.assertIn('Project files updated.', format_entry(log.snapshot()[1][-1], Translator('ja')))

    def test_errors_are_unwrapped_and_multiline_records_indented(self):
        log = ActivityLog()
        error = ValidationError(msg('Generation failed.\n{error}', error='permission denied'))
        log.add(error, 'error')
        entry = log.snapshot()[1][0]
        self.assertIs(entry.message, error.message)
        text = format_entry(entry, Translator('ja'))
        self.assertIn('生成に失敗しました。', text)
        self.assertTrue(text.splitlines()[1].startswith(' '))

    def test_no_empty_records_or_invalid_level(self):
        log = ActivityLog()
        log.add(''); log.add('hi', 'weird')
        self.assertEqual(1, len(log.snapshot()[1]))
        self.assertEqual('info', log.snapshot()[1][0].level)

    def test_bad_limits_rejected(self):
        for kwargs in ({'max_entries': 0}, {'max_chars': -1}):
            with self.assertRaises(ValueError): ActivityLog(**kwargs)

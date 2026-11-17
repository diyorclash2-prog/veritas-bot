"""Exercise the real CI runner with tiny, offline baseline/candidate repositories."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


VERIFY = Path(__file__).parent / '.github' / 'repair' / 'verify.py'
REGRESSION = 'test_repair_case_fixture.py'


class BaselineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before, self.after = self.root/'before', self.root/'after'
        self.before.mkdir()
        self.after.mkdir()
        (self.before/'bot.py').write_text('VALUE = 1\n')
        (self.after/'bot.py').write_text('VALUE = 2\n')

    def run_ci(self, body, *, auto=True):
        (self.after/REGRESSION).write_text(body)
        return subprocess.run([sys.executable,'-I',str(VERIFY),str(self.after),str(self.before)],
            capture_output=True,text=True,timeout=25,
            env={**os.environ,'AUTOREPAIR':str(auto).lower(),'PYTHONDONTWRITEBYTECODE':'1'})

    def test_file_relative_regression_reads_old_source_then_new_source(self):
        result = self.run_ci('''import unittest
from pathlib import Path
class TestSource(unittest.TestCase):
    def test_changed_value(self):
        self.assertEqual(Path(__file__).with_name('bot.py').read_text(), 'VALUE = 2\\n')
''')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('FAILED (failures=1)',result.stderr)
        self.assertIn('OK',result.stderr)
        self.assertEqual((self.before/'bot.py').read_text(),'VALUE = 1\n')
        self.assertFalse((self.before/REGRESSION).exists())
        self.assertEqual((self.after/'bot.py').read_text(),'VALUE = 2\n')

    def test_import_and_working_directory_use_same_baseline(self):
        result = self.run_ci('''import unittest
from pathlib import Path
from bot import VALUE
class TestSource(unittest.TestCase):
    def test_changed_value(self):
        self.assertEqual(Path('bot.py').read_text(), f'VALUE = {VALUE}\\n')
        self.assertEqual(VALUE, 2)
''')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('FAILED (failures=1)',result.stderr)

    def test_test_passing_on_old_code_is_still_rejected(self):
        result = self.run_ci('''import unittest
class MeaninglessTest(unittest.TestCase):
    def test_always_true(self): self.assertTrue(True)
''')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Regression must fail on the old code',result.stderr)

    def test_candidate_failure_is_not_ignored(self):
        result = self.run_ci('''import unittest
from pathlib import Path
class BadFixTest(unittest.TestCase):
    def test_changed_value(self):
        self.assertEqual(Path(__file__).with_name('bot.py').read_text(), 'VALUE = 3\\n')
''')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stderr.count('FAILED (failures=1)'),2)

    def test_existing_tests_cannot_be_overwritten_by_automatic_repair(self):
        (self.before/REGRESSION).write_text('import unittest\n')
        result = self.run_ci('import unittest\n# replacement\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Protected file changed',result.stderr)

    def test_manual_changes_still_run_all_candidate_tests(self):
        result = self.run_ci('''import unittest
from bot import VALUE
class TestSource(unittest.TestCase):
    def test_changed_value(self): self.assertEqual(VALUE,2)
''',auto=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stderr.count('Ran 1 test'),1)


if __name__ == '__main__':
    unittest.main()

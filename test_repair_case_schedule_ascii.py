"""Regression coverage for schedules compared to ASCII strftime output."""
from pathlib import Path
import tempfile
import unittest

from lingua_bot_bridge import Config, Store, schedule


class ScheduleAsciiTests(unittest.TestCase):
    def test_all_valid_ascii_times_are_preserved(self):
        for hour in range(24):
            for minute in range(60):
                value = f'{hour:02d}:{minute:02d}'
                with self.subTest(value=value):
                    self.assertEqual(schedule(value, 'UTC'), (value, 'UTC'))

    def test_unicode_digits_cannot_corrupt_persisted_schedule(self):
        # Python's regex \d includes these digits, but strftime produces ASCII.
        invalid_times = ('1\u0669:00', '19:0\u0661', '0\uff19:30', '19:5\uff19')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'schedule.sqlite3'
            config = Config(hour='19:00', tz='UTC', enabled=True)
            store = Store(path, config)
            original = store.settings()
            for value in invalid_times:
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        schedule(value, 'UTC')
                    with self.assertRaises(ValueError):
                        store.configure(hour=value, tz='UTC')
                    self.assertEqual(store.settings(), original)
                    self.assertEqual(Store(path, config).settings(), original)


if __name__ == '__main__':
    unittest.main()

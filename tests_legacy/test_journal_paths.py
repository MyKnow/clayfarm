import concurrent.futures
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from clayfarm.journal import Journal
from clayfarm.util import native_path


class JournalPathTests(unittest.TestCase):
    def test_existing_pending_outbox_survives_path_alias_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'worker.sqlite'
            original = Journal(path)
            task = {'id': 'pending-task', 'attempt_id': 'original-attempt'}
            result = {'files': [{'local': 'existing-artifact.glb'}], 'fingerprint': 'original'}
            original.save(task, 'pending', result)
            reopened = Journal(native_path(path))
            if os.name == 'nt':
                self.assertEqual(reopened.path, original.path)
            self.assertEqual(reopened.entry(task['id'])['result'], result)
            self.assertEqual(reopened.entry(task['id'])['task'], task)
            self.assertEqual(Journal(path).state(task['id']), 'pending')

    def test_status_and_worker_aliases_can_write_concurrently(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'worker.sqlite'
            journals = [Journal(path), Journal(native_path(path))]
            def write_batch(index):
                journal = journals[index % 2]
                for n in range(20):
                    journal.put(f'{index}-{n}', {'value': n})
                    self.assertEqual(journal.get(f'{index}-{n}'), {'value': n})
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(write_batch, range(4)))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('pragma integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('select count(*) from kv').fetchone()[0], 80)


if __name__ == '__main__':
    unittest.main()

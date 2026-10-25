"""Check handle closure before temp cleanup, even on platforms that allow unlinking open files."""
import sqlite3
import tempfile
import pytest
from career_pipeline import evaluation
from career_pipeline.store import Store


@pytest.mark.parametrize('failure_stage', [None, 'run', 'judge'])
def test_evaluation_closes_every_database_before_directory_cleanup(tmp_path, monkeypatch, failure_stage):
    stores = []
    cleaned = []
    real_directory = tempfile.TemporaryDirectory

    class TrackedStore(Store):
        def __init__(self, path):
            super().__init__(path)
            stores.append(self)  # Retain references so garbage collection cannot hide a leak.

    class CheckedDirectory(real_directory):
        def __exit__(self, *args):
            try:
                for store in stores:
                    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                        store.db.execute('SELECT 1')
                cleaned.append(True)
            finally:
                # Also allow cleanup on Windows if a regression causes the assertion to fail.
                for store in stores:
                    store.close()
                super().__exit__(*args)

    monkeypatch.setattr(evaluation, 'Store', TrackedStore)
    monkeypatch.setattr(evaluation.tempfile, 'TemporaryDirectory', CheckedDirectory)
    if failure_stage:
        def fail(*args, **kwargs):
            raise RuntimeError('synthetic evaluation failure')
        monkeypatch.setattr(evaluation, failure_stage, fail)
        with pytest.raises(RuntimeError, match='synthetic evaluation failure'):
            evaluation.evaluate(str(tmp_path/'evaluation.json'))
        assert not (tmp_path/'evaluation.json').exists()
    else:
        assert len(evaluation.evaluate(str(tmp_path/'evaluation.json'))['results']) == 6
    assert len(stores) == (1 if failure_stage else 6)
    assert cleaned == [True]

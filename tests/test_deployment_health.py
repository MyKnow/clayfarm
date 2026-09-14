import importlib.util
import io
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('deployment_health', Path(__file__).resolve().parents[1] / 'deploy/healthcheck.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


@pytest.mark.parametrize('backend,parallel,farm,permission,expected', [
    ('public.cf_jobs/cf_tasks', False, 'existing-farm', True, 0),
    ('development_fixture_queue', True, 'existing-farm', True, 1),
    ('public.cf_jobs/cf_tasks', False, 'wrong-farm', True, 1),
    ('public.cf_jobs/cf_tasks', False, 'existing-farm', False, 1),
])
def test_only_bound_authorized_central_queue_is_ready(monkeypatch, backend, parallel, farm, permission, expected):
    monkeypatch.setenv('CLAYFARM_DATABASE_URL', 'postgresql+psycopg://fixture')
    monkeypatch.setenv('CLAYFARM_FARM_ID', 'existing-farm')
    monkeypatch.setattr(health, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps({
        'status': 'ok', 'queue_backend': backend, 'parallel_queue_enabled': parallel,
    }).encode()))
    results = iter([farm, permission])

    class Engine:
        disposed = False

        @contextmanager
        def connect(self):
            yield self

        def execute(self, statement):
            return self

        def scalar_one(self):
            return next(results)

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr(health, 'create_engine', lambda *a, **kw: engine)
    assert health.main() == expected
    if not parallel:
        assert engine.disposed


def test_outage_is_unready_without_printing_connection_secrets(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise RuntimeError('credential-like internal detail must not be printed')
    monkeypatch.setattr(health, 'urlopen', unavailable)
    assert health.main() == 1
    assert capsys.readouterr() == ('', '')

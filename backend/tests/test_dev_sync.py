"""Isolated workflow checks: no SSH, Docker, production or real dev writes."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.admin import dev_sync_service as sync
from app.routers.dev_sync_router import router


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, 'ROOT', tmp_path / 'sync')
    monkeypatch.setattr(sync, 'allowed', lambda: True)
    monkeypatch.setattr(sync, '_check_target', lambda: None)
    sync.ROOT.mkdir()
    folder = sync.ROOT / ('a' * 32)
    folder.mkdir()
    sync._write(sync.ROOT / 'state.json', {'id': folder.name, 'status': 'idle'})
    return folder


def snapshot(signature='same'):
    return dict(tables={'financial_reports': 1, 'companies': 1},
                reports=[{'id': 1, 'ticker': 'TEST', 'date': '2025-12-31', 'signature': signature}],
                financial_hash=signature, company_hash='company', schema='schema', revision='revision',
                verified=0, active_jobs=0)


def manifest(folder, local=None, source=None):
    archive = folder / 'production.dump'
    archive.write_bytes(b'PGDMPfixture')
    sync._write(folder / 'manifest.json', {'local': local or snapshot(), 'source': source or snapshot('new'),
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})


def test_no_sync_or_local_state_on_production(env, monkeypatch):
    monkeypatch.setattr(sync, 'allowed', lambda: False)
    assert sync.status()['status'] == 'unavailable'
    assert 'id' not in sync.status()
    with pytest.raises(ValueError, match='только с локальной'):
        sync.start('prepare')
    assert not sync.writes_blocked()


def test_comparison_includes_additions_changes_and_removals():
    local = snapshot()
    local['reports'].append({'id': 3, 'ticker': 'OLD', 'signature': 'gone'})
    source = snapshot('changed')
    source['reports'].append({'id': 2, 'ticker': 'NEW', 'signature': 'new'})
    result = sync.comparison(local, source)
    assert (result['added'], result['updated'], result['removed']) == (1, 1, 1)
    assert result['companies'] == [dict(ticker='NEW', added=1, updated=0, removed=0),
                                   dict(ticker='OLD', added=0, updated=0, removed=1),
                                   dict(ticker='TEST', added=0, updated=1, removed=0)]


def test_target_must_be_the_same_postgres_cluster_as_the_dev_app(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(sync, 'allowed', lambda: True)
    connection = SimpleNamespace(exec_driver_sql=lambda query: SimpleNamespace(scalar_one=lambda: 'app-cluster:dev'))
    monkeypatch.setattr(sync, 'engine', SimpleNamespace(connect=lambda: nullcontext(connection)))
    monkeypatch.setattr(sync, '_sql', lambda db, query: 'different-cluster:dev')
    with pytest.raises(ValueError, match='не совпадает с базой'):
        sync._check_target()


def test_reused_numeric_id_does_not_hide_a_deleted_local_report():
    local = snapshot(); source = snapshot('different-report')
    source['reports'][0]['ticker'] = 'OTHER'
    result = sync.comparison(local, source)
    assert (result['added'], result['removed'], result['updated']) == (1, 1, 0)


def test_download_is_read_only_and_excludes_all_auth_tables_and_sequences(env, monkeypatch):
    calls = []
    monkeypatch.setattr(sync, '_run', lambda args, **kw: calls.append((args, kw['data'].decode())))
    monkeypatch.delenv('DEV_SYNC_SERVER', raising=False)
    sync._download(env / 'dump', None)
    args, script = calls[0]
    assert args[0] == 'ssh' and 'BatchMode=yes' in args
    assert 'pg_dump' in script and 'pg_restore' not in script
    for table in sync.AUTH:
        assert f'-T {table} ' in script and f'-T {table}_id_seq' in script


def test_restore_is_transactional_and_never_sends_dump_to_remote(env, monkeypatch):
    manifest(env)
    calls = []
    def docker(*args, **kw):
        calls.append(args)
        assert kw['stdin'].read(5) == b'PGDMP'
    monkeypatch.setattr(sync, '_docker', docker)
    sync._restore('test_dev', env / 'production.dump', None, clean=True)
    command = calls[0][3:]
    assert command[:5] == ('pg_restore', '-U', sync.settings.POSTGRES_USER, '-d', 'test_dev')
    assert '--single-transaction' in calls[0] and '--clean' in calls[0]


def test_restore_timeout_terminates_only_its_own_connection(env, monkeypatch):
    import subprocess
    manifest(env)
    calls = []
    def timeout(*a, **k): raise subprocess.TimeoutExpired('docker', 600)
    monkeypatch.setattr(sync, '_docker', timeout)
    monkeypatch.setattr(sync, '_sql', lambda db, query: calls.append((db, query)))
    with pytest.raises(RuntimeError, match='незавершённая транзакция откатывается'):
        sync._restore('test_dev', env / 'production.dump', None, clean=True)
    assert calls[0][0] == 'test_dev'
    assert "application_name='graham-dev-sync-restore'" in calls[0][1]
    assert 'datname=current_database()' in calls[0][1]


def test_prepare_checks_schema_in_temporary_db_and_always_cleans_it(env, monkeypatch):
    calls = []
    local = snapshot(); source = snapshot('new'); source['schema'] = 'different'
    monkeypatch.setattr(sync, '_snapshot', lambda db: local if db == sync.settings.POSTGRES_DB else source)
    monkeypatch.setattr(sync, '_download', lambda path, lock: path.write_bytes(b'PGDMPtest'))
    monkeypatch.setattr(sync, '_restore', lambda *a, **k: None)
    monkeypatch.setattr(sync, '_docker', lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match='Схемы prod и dev различаются'):
        sync._prepare(env, None)
    assert calls[0][0] == 'createdb' and calls[-1][0] == 'dropdb'
    assert not (env / 'manifest.json').exists()


def test_prepare_ready_does_not_restore_into_dev(env, monkeypatch):
    restores = []
    monkeypatch.setattr(sync, '_snapshot', lambda db: snapshot() if db == sync.settings.POSTGRES_DB else snapshot('new'))
    monkeypatch.setattr(sync, '_download', lambda path, lock: path.write_bytes(b'PGDMPtest'))
    monkeypatch.setattr(sync, '_restore', lambda database, *a, **k: restores.append(database))
    monkeypatch.setattr(sync, '_docker', lambda *a, **k: None)
    sync._prepare(env, None)
    assert sync._read()['status'] == 'ready' and sync._read()['preview']['updated'] == 1
    assert all(database.startswith('graham_sync_') for database in restores)


@pytest.mark.parametrize('problem', ['changed_local', 'changed_archive', 'backup_failure', 'active_jobs'])
def test_apply_refuses_unsafe_or_stale_work_before_any_restore(env, monkeypatch, problem):
    from app.services.admin import backup_service
    manifest(env)
    current = snapshot('edited') if problem == 'changed_local' else snapshot()
    if problem == 'active_jobs': current['active_jobs'] = 1
    if problem == 'changed_archive': (env / 'production.dump').write_bytes(b'tampered')
    monkeypatch.setattr(sync, '_snapshot', lambda db: current)
    def backup(): raise RuntimeError('backup failed')
    monkeypatch.setattr(backup_service, 'create_postgres_backup', backup)
    monkeypatch.setattr(sync, '_restore', lambda *a, **k: pytest.fail('Must not write'))
    with pytest.raises((ValueError, RuntimeError)):
        sync._apply(env, None)


def test_apply_backs_up_then_restores_and_verifies_auth_and_flags(env, monkeypatch):
    from app.services.admin import backup_service
    from app.services import data_cache
    manifest(env)
    calls = []
    snapshots = iter([snapshot(), snapshot(), snapshot('new')])
    monkeypatch.setattr(sync, '_snapshot', lambda db: next(snapshots))
    monkeypatch.setattr(sync, '_auth_hashes', lambda: {'users': 'unchanged'})
    monkeypatch.setattr(backup_service, 'create_postgres_backup', lambda: calls.append('backup') or {'path': '/safe/backup.dump'})
    monkeypatch.setattr(sync, '_restore', lambda *a, **k: calls.append('restore'))
    monkeypatch.setattr(data_cache, 'bump', lambda: None)
    sync._apply(env, None)
    assert calls == ['backup', 'restore']
    state = sync._read()
    assert state['status'] == 'completed' and state['result']['accounts_preserved']
    assert state['result']['verified'] == 0


def test_lock_and_orphan_recovery(env):
    sync._save(status='applying')
    handle = sync._lock()
    try:
        with pytest.raises(ValueError, match='уже выполняется'): sync.start('prepare')
        assert sync.status()['status'] == 'applying'
    finally: handle.close()
    assert sync.status()['status'] == 'failed'
    assert not sync.writes_blocked()


def test_admin_csrf_and_write_freeze(env, monkeypatch):
    import app.utils.admin_guard as guard
    app = FastAPI(); app.include_router(router)
    @app.post('/reports')
    def write(): return {'ok': True}
    app.add_middleware(guard.AdminGuardMiddleware)
    monkeypatch.setattr(guard, 'SessionLocal', lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(guard, 'current', lambda *a: None)
    client = TestClient(app)
    assert client.get('/admin/dev-sync/status').status_code == 401
    assert client.post('/admin/dev-sync/prepare').status_code == 403
    monkeypatch.setattr(guard, 'current', lambda *a: (None, SimpleNamespace(id=1, role='admin')))
    monkeypatch.setattr(guard, 'origin_allowed', lambda *a: True)
    headers = {'X-Requested-With': 'graham-analyzer', 'Origin': 'http://localhost:3000'}
    sync._save(status='applying')
    monkeypatch.setattr(sync, 'status', lambda: {'enabled': True, 'status': 'applying'})
    assert client.get('/admin/dev-sync/status').status_code == 200
    assert client.post('/reports', headers=headers).status_code == 503
    assert client.post('/admin/dev-sync/apply', headers=headers, json={'snapshot_id': '../escape'}).status_code == 422

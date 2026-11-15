"""Pull a reviewed production snapshot into local dev. Never writes to production.

SSH uses the developer's existing key. No Docker socket, SSH keys or new inbound
ports are exposed on production. Account tables and their sequences never travel.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR, settings
from app.database import engine
from app.services.dump_import import planner, worker as dump_worker

ROOT = BASE_DIR / 'data' / 'dev-sync'
AUTH = ('users', 'user_sessions', 'auth_tokens')
BUSY = {'preparing', 'applying'}
VOLATILE = ['current_price', 'price_updated_at', 'price_source', 'price_quoted_at',
            'updated_at', 'issue_size', 'issue_size_at']


def allowed():
    return planner.apply_allowed()


def now():
    return datetime.now(timezone.utc).isoformat()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def _read():
    path = ROOT / 'state.json'
    return json.loads(path.read_text()) if path.exists() else {'status': 'idle'}


def _save(**changes):
    state = _read()
    state.update(changes, updated_at=now())
    _write(ROOT / 'state.json', state)
    if state.get('id'):
        _write(ROOT / state['id'] / 'state.json', state)
    return state


def _lock():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = (ROOT / 'worker.lock').open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def status():
    enabled = allowed()
    if not enabled:
        return {'enabled': False, 'status': 'unavailable',
                'message': 'Откройте локальную админку dev: получение данных запускается с рабочей машины.'}
    state = _read()
    if state['status'] in BUSY:
        handle = _lock()
        if handle:
            try:
                # The subprocess inherits the lock: a reload cannot race a restore.
                state = _read()
                if state['status'] in BUSY:
                    state = _save(status='failed', message='Работа прервана перезапуском. Получите снимок заново; состояние записи требует сверки.')
            finally:
                handle.close()
    return {**state, 'enabled': True, 'source': 'graham-analyzer.ru → локальная dev-база'}


def writes_blocked():
    return allowed() and _read()['status'] == 'applying'


def _run(args, *, data=None, stdin=None, stdout=None, lock=None):
    result = subprocess.run(args, input=data, stdin=stdin, stdout=stdout or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=600,
                            pass_fds=(lock.fileno(),) if lock else ())
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-1800:] if result.stderr else 'Ошибка системной команды')
    return result.stdout


def _docker(*args, **kwargs):
    container = os.environ.get('POSTGRES_CONTAINER', 'graham_postgres')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', container):
        raise ValueError('Некорректное имя контейнера dev')
    return _run(['docker', 'exec', '-i', container, *args], **kwargs)


def _sql(database, query):
    return _docker('psql', '-U', settings.POSTGRES_USER, '-d', database,
                   '-At', '-v', 'ON_ERROR_STOP=1', data=query.encode()).decode().strip()


def _check_target():
    if not allowed():
        raise ValueError('Запись разрешена только в локальную dev-базу')
    query = "SELECT system_identifier::text || ':' || current_database() FROM pg_control_system()"
    with engine.connect() as connection:
        application_db = connection.exec_driver_sql(query).scalar_one()
    if _sql(settings.POSTGRES_DB, query) != application_db:
        raise ValueError('Контейнер PostgreSQL не совпадает с базой текущего dev-приложения')


def _snapshot(database):
    tables = json.loads(_sql(database, "SELECT coalesce(json_agg(tablename ORDER BY tablename),'[]') FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('users','user_sessions','auth_tokens')"))
    if any(not re.fullmatch('[a-z_]+', name) for name in tables):
        raise ValueError('Неизвестные имена таблиц в снимке')
    counts = {name: int(_sql(database, f'SELECT count(*) FROM "{name}"')) for name in tables}
    reports = json.loads(_sql(database, """SELECT coalesce(json_agg(json_build_object(
      'id',r.id,'ticker',c.ticker,'date',r.report_date,'period',r.period_type,
      'standard',r.accounting_standard,'consolidated',r.consolidated,
      'signature',md5(to_jsonb(r)::text)) ORDER BY r.id),'[]')
      FROM financial_reports r JOIN companies c ON c.id=r.company_id"""))
    financial_hash = _sql(database, "SELECT md5(coalesce(string_agg(to_jsonb(r)::text,E'\\n' ORDER BY to_jsonb(r)::text),'')) FROM financial_reports r")
    company_hash = _sql(database, "SELECT md5(coalesce(string_agg((to_jsonb(c)-ARRAY[" + ','.join("'" + f + "'" for f in VOLATILE) + "])::text,E'\\n' ORDER BY id),'')) FROM companies c")
    schema = _sql(database, """SELECT md5(string_agg(concat_ws('|',table_name,column_name,data_type,udt_name,is_nullable,column_default),E'\\n' ORDER BY table_name,ordinal_position))
      FROM information_schema.columns WHERE table_schema='public' AND table_name NOT IN ('users','user_sessions','auth_tokens')""")
    revision = _sql(database, 'SELECT string_agg(version_num,\',\' ORDER BY version_num) FROM alembic_version')
    verified = int(_sql(database, 'SELECT count(*) FROM financial_reports WHERE verified_by_analyst'))
    active = sum(int(_sql(database, f"SELECT count(*) FROM {t} WHERE status IN ('running','pending')"))
                 for t in ['mass_parse_jobs', 'disclosure_parse_jobs', 'disclosure_sync_runs'])
    return dict(tables=counts, reports=reports, financial_hash=financial_hash, company_hash=company_hash,
                schema=schema, revision=revision, verified=verified, active_jobs=active)


def _fingerprint(snapshot):
    return [snapshot['financial_hash'], snapshot['company_hash'], snapshot['schema'], snapshot['revision']]


def comparison(local, source):
    before = {r['id']: r for r in local['reports']}
    after = {r['id']: r for r in source['reports']}
    totals = dict(added=0, updated=0, removed=0)
    companies = defaultdict(lambda: dict(added=0, updated=0, removed=0))
    def identity(row):
        return tuple(row.get(field) for field in ['ticker', 'date', 'period', 'standard', 'consolidated'])
    for key in before.keys() | after.keys():
        if key in before and key in after and identity(before[key]) != identity(after[key]):
            # Independent dev/prod inserts may reuse the same numeric ID.
            # Do not hide a local report's removal behind a generic update count.
            for action, row in [('removed', before[key]), ('added', after[key])]:
                totals[action] += 1
                companies[row['ticker']][action] += 1
            continue
        action = 'added' if key not in before else 'removed' if key not in after else 'updated' if before[key]['signature'] != after[key]['signature'] else None
        if action:
            totals[action] += 1
            companies[(after.get(key) or before[key])['ticker']][action] += 1
    return {**totals, 'companies': [{'ticker': t, **counts} for t, counts in sorted(companies.items())],
            'tables': [{'name': name, 'dev': local['tables'].get(name, 0), 'prod': source['tables'].get(name, 0)}
                       for name in sorted(local['tables'].keys() | source['tables'].keys())],
            'verified_dev': local['verified'], 'verified_prod': source['verified']}


def _download(destination, lock):
    server = os.environ.get('DEV_SYNC_SERVER', 'ubuntu@185.149.147.111')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+', server):
        raise ValueError('Некорректный DEV_SYNC_SERVER')
    directory = os.environ.get('DEV_SYNC_REMOTE_DIR', '/opt/graham')
    exclude = ' '.join('-T ' + shlex.quote(t + suffix) for t in AUTH for suffix in ['', '_id_seq'])
    script = f'''set -euo pipefail
cd {shlex.quote(directory + '/deploy')}
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl {exclude}'
'''
    with destination.open('xb') as output:
        _run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', server, 'bash', '-s'],
             data=script.encode(), stdout=output, lock=lock)


def _restore(database, path, lock, clean=False):
    args = ['env', 'PGAPPNAME=graham-dev-sync-restore',
            'PGOPTIONS=-c lock_timeout=15000 -c statement_timeout=300000',
            'pg_restore', '-U', settings.POSTGRES_USER, '-d', database,
            '--no-owner', '--no-acl', '--exit-on-error', '--single-transaction']
    if clean:
        args += ['--clean', '--if-exists']
    try:
        with path.open('rb') as stream:
            _docker(*args, stdin=stream, lock=lock)
    except subprocess.TimeoutExpired as exc:
        # Killing docker exec alone can leave pg_restore running in the container.
        # End only this workflow's connection; its transaction is rolled back.
        _sql(database, "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE "
             "application_name='graham-dev-sync-restore' AND datname=current_database() AND pid<>pg_backend_pid()")
        raise RuntimeError('Тайм-аут переноса. Соединение pg_restore остановлено; незавершённая транзакция откатывается.') from exc


def _auth_hashes():
    return {table: _sql(settings.POSTGRES_DB, "SELECT md5(coalesce(string_agg((to_jsonb(t)-ARRAY['last_seen_at','last_login_at'])::text,E'\\n' ORDER BY (to_jsonb(t)-ARRAY['last_seen_at','last_login_at'])::text),'')) FROM " + table + ' t') for table in AUTH}


def _prepare(folder, lock):
    _check_target()
    local = _snapshot(settings.POSTGRES_DB)
    if local['active_jobs']:
        raise ValueError('Сначала остановите активные задачи парсинга и раскрытия в dev')
    if shutil.disk_usage(ROOT).free < 1024 ** 3:
        raise ValueError('Для снимка и временной базы нужен минимум 1 ГБ свободного места')
    _save(message='Загрузка снимка прода по SSH. Прод не изменяется.')
    archive = folder / 'production.dump'
    _download(archive, lock)
    with archive.open('rb') as stream:
        magic = stream.read(5)
    if magic != b'PGDMP':
        raise ValueError('Источник не вернул корректный custom-дамп PostgreSQL')
    _save(message='Проверка снимка в отдельной временной базе')
    staging = 'graham_sync_' + folder.name[:16]
    _docker('createdb', '-U', settings.POSTGRES_USER, staging, lock=lock)
    try:
        _restore(staging, archive, lock)
        source = _snapshot(staging)
        if source['schema'] != local['schema'] or source['revision'] != local['revision']:
            raise ValueError('Схемы prod и dev различаются. Сначала обновите код и миграции dev.')
        if source['active_jobs']:
            raise ValueError('На проде есть активные задачи. Дождитесь их завершения и получите новый снимок.')
        _write(folder / 'manifest.json', {'local': local, 'source': source,
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
    finally:
        _docker('dropdb', '-U', settings.POSTGRES_USER, '--if-exists', staging, lock=lock)
    _save(status='ready', message='Снимок проверен. Изучите изменения перед заменой dev.',
          preview=comparison(local, source), downloaded_at=now(), size_bytes=archive.stat().st_size)


def _apply(folder, lock):
    from app.services.admin.backup_service import create_postgres_backup
    from app.services import data_cache
    _check_target()
    manifest = json.loads((folder / 'manifest.json').read_text())
    current = _snapshot(settings.POSTGRES_DB)
    if _fingerprint(current) != _fingerprint(manifest['local']):
        raise ValueError('Отчёты или компании dev изменились после сравнения. Получите снимок заново.')
    if current['active_jobs']:
        raise ValueError('Сначала остановите активные задачи dev')
    archive = folder / 'production.dump'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('Контрольная сумма снимка не совпала; получите его заново')
    _save(message='Создание бэкапа dev перед заменой данных')
    backup = create_postgres_backup()
    _save(backup=backup, message='Бэкап создан. Перенос данных в dev одной транзакцией.')
    # Check again after the potentially slow backup, before any restore writes.
    if _fingerprint(_snapshot(settings.POSTGRES_DB)) != _fingerprint(current):
        raise ValueError('Данные dev изменились во время бэкапа; выполните сравнение заново')
    auth = _auth_hashes()
    _restore(settings.POSTGRES_DB, archive, lock, clean=True)
    data_cache.bump()
    after = _snapshot(settings.POSTGRES_DB)
    if _fingerprint(after) != _fingerprint(manifest['source']):
        raise RuntimeError('Перенос выполнен, но проверка данных не совпала. Сохранён бэкап для восстановления.')
    if _auth_hashes() != auth:
        raise RuntimeError('Проверка локальных аккаунтов не совпала; требуется сверка. Дамп не содержит таблиц аккаунтов.')
    _save(status='completed', message='Dev синхронизирован с проверенным снимком прода. Аккаунты сохранены.',
          completed_at=now(), result={'reports': after['tables']['financial_reports'],
          'companies': after['tables']['companies'], 'verified': after['verified'], 'accounts_preserved': True})


def _work(action, folder, handle, import_handle):
    try:
        (_prepare if action == 'prepare' else _apply)(folder, handle)
    except Exception as exc:
        _save(status='failed', message=str(exc)[-2000:])
    finally:
        import_handle.close()
        handle.close()


def start(action, snapshot_id=None):
    if not allowed():
        raise ValueError('Синхронизация разрешена только с локальной dev-базой, DEBUG=true')
    if action not in {'prepare', 'apply'}:
        raise ValueError('Неизвестное действие')
    handle = _lock()
    if handle is None:
        raise ValueError('Синхронизация уже выполняется')
    import_handle = None
    try:
        import_handle = dump_worker.acquire()
        if import_handle is None:
            raise ValueError('Сначала остановите задачу импорта из дампа')
        if action == 'prepare':
            job_id = uuid.uuid4().hex
            _write(ROOT / 'state.json', {'id': job_id, 'status': 'preparing', 'started_at': now(),
                                         'message': 'Подготовка снимка прода'})
        else:
            state = _read()
            if not snapshot_id or state.get('id') != snapshot_id or state['status'] != 'ready':
                raise ValueError('Сначала получите и проверьте актуальный снимок')
            job_id = snapshot_id
            _save(status='applying', message='Подготовка синхронизации prod → dev')
        folder = ROOT / job_id
        folder.mkdir(exist_ok=True, mode=0o700)
        threading.Thread(target=_work, args=(action, folder, handle, import_handle), daemon=True).start()
    except Exception:
        if import_handle:
            import_handle.close()
        handle.close()
        raise
    return status()

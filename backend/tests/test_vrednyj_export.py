"""Exporter checkpoints and rate-limit behavior without network or application DB."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('vrednyj_export', Path(__file__).parents[1]/'scripts/export_vrednyj.py')
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)


class Reply:
    status_code = 200
    headers = {}

    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return {'result':{'structuredContent':self.data}}


class Session:
    def __init__(self): self.headers = {}; self.calls = 0
    def post(self, url, json, timeout):
        self.calls += 1
        params = json['params']; args = params['arguments']
        if params['name'] == 'get_evidence':
            items = [{'source_id':args['source_ids'][0]}]; cursor = None
        else:
            second = bool(args.get('cursor'))
            items = [{'id':'f2' if second else 'f1','source_id':'s2' if second else 's1'}]
            cursor = None if second else 'next'
        return Reply({'dataset':{'version':'v1'},'status':'ok','items':items,'page':{'next_cursor':cursor}})


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.disk = patch.object(export.shutil,'disk_usage',return_value=SimpleNamespace(free=10*1024**3))
        self.disk.start()
        self.addCleanup(self.disk.stop)

    def seed(self, path):
        with sqlite3.connect(path) as db:
            db.executescript('CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT);'
                'CREATE TABLE jobs(id TEXT PRIMARY KEY,tool TEXT,args TEXT,done INTEGER DEFAULT 0);')
            db.execute('INSERT INTO state VALUES("seeded","1")')
            db.execute('INSERT INTO jobs VALUES(?,?,?,0)',('seed','get_series',json.dumps({'companies':['X'],'metrics':['fin.x']})))

    def test_pagination_checkpoint_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'copy.sqlite'; self.seed(path); session = Session()
            with patch.object(export.requests,'Session',return_value=session), patch.object(export.time,'sleep'):
                export.run(path,1)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM facts').fetchone()[0],1)
                export.run(path,10)
                calls = session.calls
                export.run(path,10)
                self.assertEqual(session.calls,calls)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM facts').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM evidence').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM jobs WHERE done=0').fetchone()[0],0)

    def test_429_keeps_job_and_cooldown(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'copy.sqlite'; self.seed(path)
            session=Session(); response=Reply({}); response.status_code=429; response.headers={'Retry-After':'120'}
            with patch.object(export.requests,'Session',return_value=session), patch.object(session,'post',return_value=response):
                export.run(path,10)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT done FROM jobs').fetchone()[0],0)
                    self.assertGreater(float(db.execute('SELECT value FROM state WHERE key="retry_not_before"').fetchone()[0]),export.time.time())
                with self.assertRaises(SystemExit): export.run(path,1)

    def test_storage_guard_prevents_request(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'copy.sqlite'; self.seed(path); session=Session()
            with patch.object(export.requests,'Session',return_value=session), patch.object(export.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
                export.run(path,1)
            self.assertEqual(session.calls,0)


if __name__ == '__main__': unittest.main()

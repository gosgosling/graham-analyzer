"""Bounded background continuation; honors checkpoints and Retry-After."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
folder = root/'data/external/vrednyj-investor/2026-11-01'
database = folder/'public.sqlite'
status = folder/'worker.status.json'
started = time.time()
state = 'running'
try:
    for batch in range(40):
        if (folder/'STOP').exists() or time.time()-started > 4*3600:
            state = 'stopped_by_limit_or_stop_file'; break
        with sqlite3.connect(database) as db:
            pending = db.execute('SELECT count(*) FROM jobs WHERE done=0').fetchone()[0]
            before = db.execute('SELECT count(*) FROM jobs WHERE done=1').fetchone()[0]
            retry = db.execute('SELECT value FROM state WHERE key="retry_not_before"').fetchone()
        if not pending:
            state = 'search_traversal_finished'; break
        status.write_text(json.dumps({'state':'running','pid':os.getpid(),'started_unix':started,'batch':batch,'pending_jobs':pending}))
        if retry:
            wait = float(retry[0])-time.time()
            if wait > 3600:
                state = 'rate_limit_requires_later_resume'; break
            while wait > 0:
                time.sleep(min(wait,30)); wait = float(retry[0])-time.time()
                if (folder/'STOP').exists():
                    state = 'stopped_by_stop_file'; break
            if state != 'running': break
        result = subprocess.run([sys.executable,str(root/'backend/scripts/export_vrednyj.py'),
            '--output',str(database),'--max-calls','250'],cwd=root)
        with sqlite3.connect(database) as db:
            after = db.execute('SELECT count(*) FROM jobs WHERE done=1').fetchone()[0]
            retry = db.execute('SELECT value FROM state WHERE key="retry_not_before"').fetchone()
        if result.returncode or (after==before and not (retry and float(retry[0])>time.time())):
            state = 'stopped_error_or_no_progress'; break
    else:
        state = 'stopped_by_batch_limit'
except Exception as exc:
    state = 'error: '+str(exc)
finally:
    status.write_text(json.dumps({'state':state,'pid':os.getpid(),'started_unix':started,'finished_unix':time.time()},ensure_ascii=False,indent=2))

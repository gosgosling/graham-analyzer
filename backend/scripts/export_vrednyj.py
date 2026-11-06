"""Read-only, resumable copy of the public MCP numerical dataset into SQLite.

No Graham imports, credentials, production writes, or PDF downloads.
Completeness is relative to the documented alphanumeric search traversal;
the server exposes no authoritative total or bulk-export method.
"""
import argparse
import hashlib
import json
import sqlite3
import string
import time
import shutil
from pathlib import Path

import requests

URL = 'https://mcp.vrednyj-investor.ru/mcp'


def run(path, max_calls):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript('''
      CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, tool TEXT, args TEXT, done INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS responses(id TEXT PRIMARY KEY, payload TEXT);
      CREATE TABLE IF NOT EXISTS companies(id TEXT PRIMARY KEY, payload TEXT);
      CREATE TABLE IF NOT EXISTS metrics(id TEXT PRIMARY KEY, payload TEXT);
      CREATE TABLE IF NOT EXISTS variants(company TEXT, metric TEXT, selector TEXT, payload TEXT,
        PRIMARY KEY(company,metric,selector));
      CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, payload TEXT);
      CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, payload TEXT);
    ''')

    def enqueue(tool, args):
        encoded = json.dumps(args, sort_keys=True)
        key = hashlib.sha256((tool + encoded).encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO jobs(id,tool,args) VALUES(?,?,?)', (key,tool,encoded))

    if not db.execute('SELECT 1 FROM state WHERE key="seeded"').fetchone():
        for q in string.ascii_uppercase + string.digits:
            enqueue('search_companies', {'query_text':q,'limit':100})
        enqueue('search_companies', {'query_text':'АО','limit':100})
        for q in string.ascii_lowercase + string.digits:
            enqueue('find_metrics', {'query_text':q,'limit':100})
        db.execute('INSERT INTO state VALUES("seeded","1")')
        db.commit()
    def resolve_truncated(data, args):
        for item in data.get('items',[]):
            if not item.get('details_truncated'):
                continue
            companies = args.get('companies')
            if companies and len(companies) == 1:
                db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',
                    ('unresolved:'+companies[0]+':'+item['code'],'variant list truncated'))
                continue
            tickers = companies or [json.loads(r[0])['ticker'] for r in db.execute('SELECT payload FROM companies')]
            size = 1 if companies else 10
            for start in range(0,len(tickers),size):
                enqueue('find_metrics',{'query_text':item['code'],'companies':tickers[start:start+size],'limit':100})

    for encoded, payload in db.execute('SELECT j.args,r.payload FROM jobs j JOIN responses r ON j.id=r.id WHERE j.tool="find_metrics"').fetchall():
        resolve_truncated(json.loads(payload),json.loads(encoded))
    db.commit()
    session = requests.Session()
    session.headers['Accept'] = 'application/json, text/event-stream'
    cooldown = db.execute('SELECT value FROM state WHERE key="retry_not_before"').fetchone()
    if cooldown and float(cooldown[0]) > time.time():
        raise SystemExit('Rate limit cooldown active; retry after '+time.ctime(float(cooldown[0])))
    for number in range(max_calls):
        if number % 100 == 0 and (shutil.disk_usage(path.parent).free < 5*1024**3 or path.stat().st_size > 80*1024**3):
            print('Storage guard reached; checkpoint preserved.',flush=True)
            break
        job = db.execute('SELECT id,tool,args FROM jobs WHERE done=0 ORDER BY CASE tool WHEN "get_series" THEN 0 WHEN "get_evidence" THEN 1 WHEN "search_companies" THEN 2 ELSE 3 END,rowid LIMIT 1').fetchone()
        if job is None:
            break
        key, tool, encoded = job
        args = json.loads(encoded)
        try:
            response = session.post(URL, json={'jsonrpc':'2.0','id':number+1,'method':'tools/call',
                'params':{'name':tool,'arguments':args}},timeout=(10,30))
            if response.status_code == 429:
                retry = response.headers.get('Retry-After','60')
                seconds = int(retry) if retry.isdigit() else 60
                db.execute('INSERT OR REPLACE INTO state VALUES("retry_not_before",?)',(str(time.time()+max(seconds,60)),))
                db.commit()
                print('HTTP 429; Retry-After:',retry,'; checkpoint preserved.',flush=True)
                break
            response.raise_for_status()
            envelope = response.json()
            if 'error' in envelope:
                raise RuntimeError(str(envelope['error']))
            result = envelope['result']
            if result.get('isError'):
                raise RuntimeError(str(result.get('content')))
            data = result.get('structuredContent')
            if data is None:
                data = json.loads(next(c['text'] for c in result['content'] if c['type']=='text'))
            version = data.get('dataset',{}).get('version')
            existing = db.execute('SELECT value FROM state WHERE key="dataset_version"').fetchone()
            if existing and version and existing[0] != version:
                raise RuntimeError('Dataset version changed; use a new SQLite file.')
            if version:
                db.execute('INSERT OR IGNORE INTO state VALUES("dataset_version",?)',(version,))
            if data.get('status') in ('invalid_request','version_expired'):
                raise RuntimeError(str(data))
            db.execute('INSERT OR REPLACE INTO responses VALUES(?,?)',(key,json.dumps(data,ensure_ascii=False)))
            for item in data.get('items',[]):
                packed = json.dumps(item,ensure_ascii=False)
                if tool == 'search_companies':
                    db.execute('INSERT OR REPLACE INTO companies VALUES(?,?)',(item['id'],packed))
                elif tool == 'find_metrics':
                    db.execute('INSERT OR REPLACE INTO metrics VALUES(?,?)',(item['id'],packed))
                    # Global definitions cap their variant lists. Resolve details per
                    # company after discovering each available company/metric pair.
                    for v in item.get('variants',[]):
                        db.execute('INSERT OR REPLACE INTO variants VALUES(?,?,?,?)',
                            (v['ticker'],item['code'],v['selector'],json.dumps(v,ensure_ascii=False)))
                        if not args.get('companies'):
                            enqueue('find_metrics', {'query_text':item['code'],'companies':[v['ticker']],'limit':100})
                    if args.get('companies'):
                        for v in item.get('variants',[]):
                            enqueue('get_series', {'companies':[v['ticker']],'metrics':[item['code']],
                                'variants':[v['selector']],'revisions':'all_verified','limit':100})
                elif tool == 'get_series':
                    db.execute('INSERT OR REPLACE INTO facts VALUES(?,?)',(item['id'],packed))
                elif tool == 'get_evidence':
                    db.execute('INSERT OR REPLACE INTO evidence VALUES(?,?)',(item['source_id'],packed))
            if tool == 'find_metrics':
                resolve_truncated(data,args)
            if tool == 'get_series':
                sources = sorted({item['source_id'] for item in data.get('items',[])})
                for start in range(0,len(sources),20):
                    enqueue('get_evidence',{'source_ids':sources[start:start+20],'limit':100})
            cursor = data.get('page',{}).get('next_cursor')
            if cursor:
                enqueue(tool,{**args,'cursor':cursor})
            db.execute('UPDATE jobs SET done=1 WHERE id=?',(key,))
            db.commit()
            if number % 20 == 0:
                print(json.dumps(stats(db),ensure_ascii=False),flush=True)
            time.sleep(1.25)
        except Exception as exc:
            db.rollback()
            print('Stopped with checkpoint preserved:',str(exc)[:800],flush=True)
            break
    result = stats(db)
    result['bytes'] = path.stat().st_size
    result['path'] = str(path)
    result['unresolved_truncations'] = db.execute('SELECT count(*) FROM state WHERE key LIKE "unresolved:%"').fetchone()[0]
    result['completeness'] = 'partial' if result['pending_jobs'] or result['unresolved_truncations'] else 'search_traversal_finished_not_authoritative_bulk_export'
    path.with_suffix('.status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    db.close()


def stats(db):
    return {**{t:db.execute('SELECT count(*) FROM '+t).fetchone()[0]
               for t in ('companies','metrics','variants','facts','evidence')},
            'completed_jobs':db.execute('SELECT count(*) FROM jobs WHERE done=1').fetchone()[0],
            'pending_jobs':db.execute('SELECT count(*) FROM jobs WHERE done=0').fetchone()[0]}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-calls',type=int,default=100)
    args=p.parse_args()
    if args.max_calls < 1: p.error('--max-calls must be positive')
    run(args.output,args.max_calls)

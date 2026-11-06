from __future__ import annotations
import json,os,sqlite3,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from app.config import BASE_DIR

ROOT=Path(os.environ['DUMP_IMPORT_DIR']) if os.environ.get('DUMP_IMPORT_DIR') else BASE_DIR/'data'/'dump-import'

def now():return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection():
 ROOT.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(ROOT/'jobs.sqlite',timeout=20)
 try:
  db.row_factory=sqlite3.Row
  db.execute('PRAGMA journal_mode=WAL')
  db.executescript('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS items(job_id TEXT,ticker TEXT,payload TEXT NOT NULL,PRIMARY KEY(job_id,ticker)); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,job_id TEXT,at TEXT,message TEXT);')
  with db:yield db
 finally:db.close()

def create(tickers,refresh,protected):
 job={'id':uuid.uuid4().hex,'created_at':now(),'updated_at':now(),'status':'pending','phase':'audit',
      'refresh':refresh,'protected':sorted(protected),'tickers':tickers,'message':'Задача создана','backup':None,'retry_at':None}
 with connection() as db:
  db.execute('INSERT INTO jobs VALUES(?,?)',(job['id'],json.dumps(job)))
  for ticker in tickers:
   item={'ticker':ticker,'status':'pending','message':'Ожидает аудита','summary':None}
   db.execute('INSERT INTO items VALUES(?,?,?)',(job['id'],ticker,json.dumps(item)))
 return job

def get(job_id):
 with connection() as db:row=db.execute('SELECT payload FROM jobs WHERE id=?',(job_id,)).fetchone()
 if row is None:raise KeyError('Задача не найдена')
 return json.loads(row[0])

def jobs():
 with connection() as db:rows=db.execute('SELECT payload FROM jobs ORDER BY rowid DESC LIMIT 100').fetchall()
 return [json.loads(row[0]) for row in rows]

def update(job_id,**changes):
 with connection() as db:
  db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT payload FROM jobs WHERE id=?',(job_id,)).fetchone()
  if row is None:raise KeyError('Задача не найдена')
  job=json.loads(row[0]);job.update(changes,updated_at=now())
  db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(job),job_id))
 return job

def items(job_id):
 with connection() as db:rows=db.execute('SELECT payload FROM items WHERE job_id=? ORDER BY rowid',(job_id,)).fetchall()
 return [json.loads(row[0]) for row in rows]

def item_update(job_id,ticker,**changes):
 with connection() as db:
  db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT payload FROM items WHERE job_id=? AND ticker=?',(job_id,ticker)).fetchone()
  if row is None:raise KeyError('Компания в задаче не найдена')
  item=json.loads(row[0]);item.update(changes)
  db.execute('UPDATE items SET payload=? WHERE job_id=? AND ticker=?',(json.dumps(item),job_id,ticker))
 return item

def event(job_id,message):
 with connection() as db:db.execute('INSERT INTO events(job_id,at,message) VALUES(?,?,?)',(job_id,now(),message[:2000]))

def events(job_id,after=0):
 with connection() as db:rows=db.execute('SELECT id,at,message FROM events WHERE job_id=? AND id>? ORDER BY id DESC LIMIT 100',(job_id,after)).fetchall()
 return [dict(row) for row in rows]

def artifact(job_id,ticker,name):
 # Identifiers always originate in persisted jobs, never in a client filesystem path.
 job=get(job_id)
 if ticker not in job['tickers']:raise KeyError('Компания в задаче не найдена')
 path=ROOT/'runs'/job_id/ticker
 path.mkdir(parents=True,exist_ok=True)
 return path/name

def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,default=str));temporary.replace(path)

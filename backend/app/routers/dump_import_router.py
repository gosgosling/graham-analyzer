"""Admin-only dump workflow. Existing /admin middleware protects reads and writes."""
import json,re
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,field_validator
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.company import Company
from app.services.dump_import import store,planner,worker

router=APIRouter(prefix='/admin/dump-import',tags=['admin-dump-import'])

class JobCreate(BaseModel):
 tickers:list[str]=Field(min_length=1,max_length=500)
 refresh:bool=True
 @field_validator('tickers')
 @classmethod
 def valid_tickers(cls,value):
  result=list(dict.fromkeys(t.strip().upper() for t in value))
  if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,24}',t) for t in result):raise ValueError('Некорректный тикер')
  return result

def job_out(job):
 items=store.items(job['id']);counts={status:sum(i['status']==status for i in items) for status in ['pending','running','audited','done','error','skipped']}
 return {**job,'counts':counts,'total':len(items),'worker_alive':worker.alive() if job['status']=='running' else False,
         'totals':{key:sum((i.get('summary') or {}).get(key,0) for i in items) for key in ['facts','add','matches','differences','blocked','new_reports']}}

def guarded(fn):
 try:return fn()
 except KeyError as exc:raise HTTPException(404,str(exc)) from exc
 except ValueError as exc:raise HTTPException(409,str(exc)) from exc

@router.get('/overview')
def overview(db:Session=Depends(get_db)):
 protected=planner.protected_tickers(db)
 companies=[{'ticker':c.ticker,'name':c.name,'company_id':c.id,'kind':planner.company_kind(c),'protected':c.ticker in protected,
             'excluded':planner.company_kind(c)=='holding'} for c in db.query(Company).order_by(Company.ticker)]
 return {'companies':companies,'apply_allowed':planner.apply_allowed(),'policy_version':planner.POLICY_VERSION,
  'rules':['Заполненные поля сохраняются; различия видны в аудите.',
           'Защищённым компаниям добавляются только отсутствующие квартальные и полугодовые отчёты.',
           'Холдинги исключены; прибыль ЛУКОЙЛа защищена.',
           'Все исходные факты сохраняются, в том числе не имеющие полей в модели.',
           'Перед переносом создаётся бэкап. Проверка аналитиком автоматически не выставляется.'],
  'storage':'data/dump-import','worker_alive':worker.alive()}

@router.get('/jobs')
def jobs():
 worker.recover()
 return [job_out(j) for j in store.jobs()]

@router.post('/jobs',status_code=201)
def create(body:JobCreate,db:Session=Depends(get_db)):
 known={c.ticker:planner.company_kind(c) for c in db.query(Company).filter(Company.ticker.in_(body.tickers))}
 missing=set(body.tickers)-known.keys()
 if missing:raise HTTPException(400,'Неизвестные компании: '+', '.join(sorted(missing)))
 if any(known[t]=='holding' for t in body.tickers):raise HTTPException(400,'Холдинги исключены из импорта')
 if worker.alive():raise HTTPException(409,'Уже работает задача импорта')
 job=store.create(body.tickers,body.refresh,planner.protected_tickers(db))
 try:worker.start(job['id'])
 except ValueError as exc:
  store.update(job['id'],status='paused',message=str(exc))
  raise HTTPException(409,str(exc)) from exc
 return job_out(store.get(job['id']))

@router.get('/jobs/{job_id}')
def get_job(job_id:str):return guarded(lambda:job_out(store.get(job_id)))

@router.get('/jobs/{job_id}/items')
def items(job_id:str):
 guarded(lambda:store.get(job_id))
 return [{k:v for k,v in item.items() if k!='receipt'} for item in store.items(job_id)]

@router.get('/jobs/{job_id}/events')
def events(job_id:str,after:int=Query(0,ge=0)):
 guarded(lambda:store.get(job_id));return store.events(job_id,after)

@router.post('/jobs/{job_id}/control/{action}')
def control(job_id:str,action:Literal['pause','resume','apply','retry','cancel']):
 def execute():
  job=store.get(job_id)
  if action in ['pause','cancel']:
   if action=='pause' and job['status']!='running':raise ValueError('Задача не запущена')
   if job['status']=='completed':raise ValueError('Задача уже завершена')
   store.update(job_id,status='paused' if action=='pause' else 'cancelled',message='Пауза запрошена' if action=='pause' else 'Задача отменена')
  elif action=='retry':
   if worker.alive():raise ValueError('Сначала остановите текущую задачу')
   if job['status']=='cancelled':raise ValueError('Создайте новую задачу')
   for item in store.items(job_id):
    if item['status']=='error':store.item_update(job_id,item['ticker'],status='pending',message='Повтор аудита после ошибки')
   store.update(job_id,status='paused',phase='audit');worker.start(job_id)
  elif action=='apply':worker.start(job_id,phase='apply')
  else:
   if job['status'] not in ['paused','failed']:raise ValueError('Продолжение доступно только после паузы или ошибки')
   worker.recover()
   # Pause during an item leaves it pending/audited after the current request exits.
   worker.start(job_id)
  return job_out(store.get(job_id))
 return guarded(execute)

@router.get('/jobs/{job_id}/companies/{ticker}')
def company_audit(job_id:str,ticker:str):
 def read():
  path=store.artifact(job_id,ticker,'audit.json')
  if not path.exists():raise KeyError('Аудит компании ещё не готов')
  data=json.loads(path.read_text())
  return {k:v for k,v in data.items() if k not in ['cells','reports','before']}
 return guarded(read)

@router.get('/jobs/{job_id}/companies/{ticker}/cells')
def cells(job_id:str,ticker:str,action:str='',offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
 def read():
  path=store.artifact(job_id,ticker,'audit.json')
  if not path.exists():raise KeyError('Аудит ещё не готов')
  cells=json.loads(path.read_text())['cells']
  if action:cells=[cell for cell in cells if cell['action']==action]
  return {'total':len(cells),'items':cells[offset:offset+limit]}
 return guarded(read)

@router.get('/jobs/{job_id}/companies/{ticker}/download/{kind}')
def download(job_id:str,ticker:str,kind:Literal['source','audit','receipt']):
 def read():
  path=store.artifact(job_id,ticker,kind+'.json')
  if not path.exists():raise KeyError('Файл ещё не создан')
  return FileResponse(path,media_type='application/json',filename=f'{ticker}-{kind}.json')
 return guarded(read)

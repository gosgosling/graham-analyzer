from __future__ import annotations
import fcntl,json,logging,threading
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.enums import AccountingStandard,PeriodType,ReportSource
from . import store,source,planner

log=logging.getLogger(__name__)

class Stopped(Exception):pass

def acquire():
 store.ROOT.mkdir(parents=True,exist_ok=True)
 handle=open(store.ROOT/'worker.lock','a+')
 try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:handle.close();return None
 return handle

def alive():
 handle=acquire()
 if handle is None:return True
 handle.close();return False

def recover():
 handle=acquire()
 if handle is None:return
 try:
  for job in store.jobs():
   if job['status']=='running':
    store.update(job['id'],status='paused',message='Работа прервана перезапуском. Можно продолжить.')
    for item in store.items(job['id']):
     if item['status']=='running':store.item_update(job['id'],item['ticker'],status='pending' if job['phase']=='audit' else 'audited')
 finally:handle.close()

def check(job_id):
 job=store.get(job_id)
 if job['status']!='running':raise Stopped()

def start(job_id,phase=None):
 handle=acquire()
 if handle is None:raise ValueError('Уже работает другая задача. Дождитесь завершения или поставьте её на паузу.')
 try:
  job=store.get(job_id)
  if job['status']=='cancelled':raise ValueError('Отменённую задачу нельзя продолжить')
  if job.get('retry_at') and datetime.fromisoformat(job['retry_at'])>datetime.now(timezone.utc):raise ValueError('Действует пауза источника до '+job['retry_at'])
  chosen=phase or job['phase']
  if chosen=='apply':
   if not planner.apply_allowed():raise ValueError('Перенос разрешён только в локальную dev-базу с DEBUG=true')
   if phase=='apply' and job['status']!='ready':raise ValueError('Сначала завершите аудит')
  elif job['status'] not in {'pending','paused','ready','completed','failed'}:raise ValueError('Задача уже запущена')
  if phase=='apply':store.update(job_id,backup=None)
  store.update(job_id,phase=chosen,status='running',retry_at=None,message='Аудит запущен' if chosen=='audit' else 'Подготовка бэкапа и переноса')
  threading.Thread(target=run,args=(job_id,handle),daemon=True,name='dump-import-'+job_id[:8]).start()
 except Exception:handle.close();raise

def _receipt(db,company_id,job_id):
 markers=[]
 for r in db.query(FinancialReport).filter_by(company_id=company_id):
  try:notes=json.loads(r.extraction_notes or '{}')
  except (ValueError,TypeError):continue
  if isinstance(notes,dict) and notes.get('dump_import_job')==job_id:markers.append({'report_id':r.id,'fields':list(notes['provenance_added'])})
 return markers

def apply_company(db,company,job,audit,raw):
 if not planner.apply_allowed():raise ValueError('Dev-only: запись запрещена для этой базы')
 # Serialize with company writes through this workflow; also lock report rows.
 company=db.query(Company).filter_by(id=company.id).with_for_update().one()
 rows=db.query(FinancialReport).filter_by(company_id=company.id).with_for_update().all()
 markers=_receipt(db,company.id,job['id'])
 if markers:
  # Report journal and data commit atomically, so a restart after commit is recoverable.
  return {'recovered':True,'reports':markers,'added':sum(len(x['fields']) for x in markers)}
 if audit['policy_version']!=planner.POLICY_VERSION:raise ValueError('Правила переноса изменились; выполните новый аудит')
 if planner.fingerprint(rows)!=audit['baseline']:raise ValueError('Данные компании изменились после аудита. Создайте новый аудит перед переносом.')
 protected=company.ticker in (set(job['protected'])|planner.protected_tickers(db))
 if planner.company_kind(company)=='holding':raise ValueError('Холдинги исключены')
 changes=[];touched=[]
 for item in audit['reports']:
  existing=next((r for r in rows if r.id==item['report_id']),None) if item['report_id'] is not None else None
  allowed,reason=planner.allowed_report(company,protected,existing,item['period_type'])
  if not allowed:raise ValueError('Защита изменилась после аудита: '+reason)
  day=date.fromisoformat(item['date'])
  if existing is None:
   duplicate=db.query(FinancialReport).filter_by(company_id=company.id,report_date=day,period_type=PeriodType(item['period_type']),accounting_standard=AccountingStandard.IFRS,consolidated=True).first()
   if duplicate:raise ValueError('Отчёт появился после аудита; выполните аудит заново')
   r=FinancialReport(company_id=company.id,report_date=day,fiscal_year=day.year,fiscal_quarter=day.month//3 if day.month in [3,9] else None,
    period_type=PeriodType(item['period_type']),accounting_standard=AccountingStandard.IFRS,consolidated=True,currency='RUB',exchange_rate=1,
    source=ReportSource.API,report_type='bank' if planner.company_kind(company)=='lender' else 'general',
    verified_by_analyst=False,auto_extracted=True,dividends_paid=None)
   db.add(r);db.flush()
  else:r=existing
  previous=r.extraction_notes or ''
  for field,value in item['fields'].items():
   if company.ticker=='LKOH' and field in {'net_income','net_income_reported'}:raise ValueError('Прибыль LKOH защищена')
   if getattr(r,field) is not None:raise ValueError('Заполненное поле изменилось после аудита: '+field)
   setattr(r,field,value);changes.append({'report_id':r.id,'date':item['date'],'field':field,'value':value})
  r.extraction_notes=json.dumps({'dump_import_job':job['id'],'source_version':raw.get('version'),
   'provenance_added':item['provenance'],'definitions':item['definitions'],'previous_model':r.extraction_model,
   'previous_notes':previous,'source_archive':str(store.artifact(job['id'],company.ticker,'source.json')),
   'audit_archive':str(store.artifact(job['id'],company.ticker,'audit.json')),
   'note':'Непроверенное дополнение. Прибыль/капитал группы могут отличаться от владельческих. Все варианты сохранены в архиве.'},ensure_ascii=False)
  r.extraction_model='Data Foundry + existing data';r.verified_by_analyst=False;r.auto_extracted=True;touched.append(r)
 db.flush()
 from app.services.analysis.multiplier_service import save_report_based_multiplier,calculate_current_multipliers,save_current_multiplier
 for r in touched:save_report_based_multiplier(db,r,commit=False)
 if touched:
  mults=calculate_current_multipliers(db,company.id)
  if mults:save_current_multiplier(db,company.id,mults,commit=False)
 db.commit()
 return {'added':len(changes),'changes':changes,'reports':[r.id for r in touched]}

def run(job_id,handle):
 try:
  job=store.get(job_id)
  if job['phase']=='apply' and not job.get('backup'):
   check(job_id)
   from app.services.admin.backup_service import create_postgres_backup
   backup=create_postgres_backup();store.update(job_id,backup=backup);store.event(job_id,'Бэкап создан перед переносом')
  for item in store.items(job_id):
   check(job_id);job=store.get(job_id);ticker=item['ticker']
   if job['phase']=='audit' and item['status'] not in {'pending','running'}:continue
   if job['phase']=='apply' and item['status']!='audited':continue
   store.item_update(job_id,ticker,status='running',message='Загрузка и аудит' if job['phase']=='audit' else 'Перенос')
   store.update(job_id,message=ticker+': '+('загрузка / аудит' if job['phase']=='audit' else 'перенос'))
   store.event(job_id,ticker+': начало '+job['phase'])
   try:
    with SessionLocal() as db:
     company=db.query(Company).filter_by(ticker=ticker).one()
     if planner.company_kind(company)=='holding':
      store.item_update(job_id,ticker,status='skipped',message='Холдинг исключён владельцем');continue
     path=store.artifact(job_id,ticker,'source.json')
     if job['phase']=='audit':
      db.rollback()
      if path.exists():raw=json.loads(path.read_text())
      elif job['refresh']:
       raw=source.fetch(ticker,path.parent/'pages',lambda msg:store.event(job_id,msg),lambda:check(job_id));store.write(path,raw)
      else:raw=source.local(ticker);store.write(path,raw)
      check(job_id)
      # A download can take minutes. Do not retain a stale DB transaction during it.
      db.rollback();company=db.query(Company).filter_by(ticker=ticker).one()
      protected=ticker in (set(job['protected'])|planner.protected_tickers(db))
      report=planner.audit(db,company,raw,protected);store.write(store.artifact(job_id,ticker,'audit.json'),report)
      store.item_update(job_id,ticker,status='audited',summary=report['summary'],message='Аудит готов')
     else:
      raw=json.loads(path.read_text());report=json.loads(store.artifact(job_id,ticker,'audit.json').read_text())
      check(job_id);receipt=apply_company(db,company,job,report,raw)
      store.write(store.artifact(job_id,ticker,'receipt.json'),receipt)
      store.item_update(job_id,ticker,status='done',message=f"Добавлено {receipt['added']} полей",receipt=receipt)
    store.event(job_id,ticker+': готово')
   except Stopped:
    store.item_update(job_id,ticker,status='pending' if job['phase']=='audit' else 'audited',message='Пауза');raise
   except source.RateLimited as exc:
    store.item_update(job_id,ticker,status='pending',message=str(exc))
    store.update(job_id,status='paused',retry_at=(datetime.now(timezone.utc)+timedelta(seconds=exc.seconds)).isoformat(),message=str(exc));store.event(job_id,str(exc));return
   except Exception as exc:
    log.exception('Dump import %s %s',job_id,ticker)
    store.item_update(job_id,ticker,status='error',message=str(exc)[:1200]);store.event(job_id,ticker+': '+str(exc)[:1200])
  check(job_id)
  items=store.items(job_id);errors=sum(i['status']=='error' for i in items)
  status='ready' if job['phase']=='audit' else 'completed'
  store.update(job_id,status=status,message=('Аудит готов' if status=='ready' else 'Перенос завершён')+f'; ошибок: {errors}')
 except Stopped:pass
 except Exception as exc:
  log.exception('Dump import worker failed')
  store.update(job_id,status='failed',message=str(exc)[:1200]);store.event(job_id,str(exc)[:1200])
 finally:handle.close()

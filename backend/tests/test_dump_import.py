"""Workflow tests against isolated SQLite: no production DB, network or real imports."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import Base,get_db
from app.models import Company,FinancialReport
from app.models.enums import PeriodType,AccountingStandard
from app.services.dump_import import planner,store,worker,source
from app.routers.dump_import_router import router

@pytest.fixture
def env(tmp_path,monkeypatch):
 engine=create_engine('sqlite:///'+str(tmp_path/'reports.sqlite'))
 Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
 monkeypatch.setattr(store,'ROOT',tmp_path/'workflow')
 monkeypatch.setattr(worker,'SessionLocal',factory)
 monkeypatch.setattr(planner,'protected_tickers',lambda db:set())
 monkeypatch.setattr(planner,'apply_allowed',lambda:True)
 with factory() as db:
  c=Company(ticker='TEST',figi='TEST',name='Test',company_type='industrial');db.add(c);db.commit()
 yield factory
 engine.dispose()

def fact(code='fin.revenue',value='2000000',end='2025-12-31',start='2025-01-01',identity='a'):
 return {'id':identity,'source_id':'src-'+identity,'ticker':'TEST','metric_code':code,'value':value,
  'accounting_basis':'IFRS','consolidation_scope':'consolidated','currency':'RUB','unit':'currency',
  'dimensions':{},'status':'canonical','review_status':'machine_validated',
  'period':{'start':start,'end':end,'kind':'duration' if start else 'instant'}}

def raw(*facts):return {'facts':list(facts),'metrics':[],'version':'test','origin':'fixture','completeness':'fixture'}

def report(db,**extra):
 c=db.query(Company).one()
 r=FinancialReport(company_id=c.id,report_date=date(2025,12,31),fiscal_year=2025,period_type=PeriodType.ANNUAL,
  accounting_standard=AccountingStandard.IFRS,consolidated=True,currency='RUB',verified_by_analyst=False,**extra)
 db.add(r);db.commit();return r

def test_audit_preserves_differences_and_keeps_all_raw_facts(env):
 with env() as db:
  r=report(db,revenue=1)
  staged=raw(fact(),fact('fin.net_income','-500000',identity='profit'),fact('fin.eps_basic','1.2',identity='eps'))
  staged['facts'][-1]['unit']='currency_per_share'
  a=planner.audit(db,db.query(Company).one(),staged,False)
  assert a['summary']['differences']==1
  assert a['summary']['add']==2
  assert a['unmapped_metrics']==['fin.eps_basic']
  assert a['not_projected']
  assert r.revenue==1
  assert len(staged['facts'])==3
  assert a['audit_projected']['reports']==1

def test_protected_company_only_missing_interim_reports(env):
 with env() as db:
  report(db,revenue=1)
  data=raw(fact(),fact('fin.operating_profit','1000000',identity='op'),fact(end='2026-06-30',start='2026-01-01',identity='h1'),fact(end='2026-12-31',start='2026-01-01',identity='fy'))
  a=planner.audit(db,db.query(Company).one(),data,True)
  assert len(a['reports'])==1
  assert a['reports'][0]['period_type']=='semi_annual'
  assert a['summary']['blocked']==3

def test_lkoh_profit_and_holding_exclusion(env):
 with env() as db:
  c=db.query(Company).one();c.ticker='LKOH';db.commit()
  data=raw(fact('fin.net_income',value='-1000000000000'))
  for f in data['facts']:f['ticker']='LKOH'
  a=planner.audit(db,c,data,False)
  assert not a['reports'] and a['summary']['blocked']==2
  c.company_type='holding'
  assert not planner.allowed_report(c,False,None,'semi_annual')[0]

def test_apply_fill_only_receipt_recovery_and_stale_plan(env,monkeypatch):
 from app.services.analysis import multiplier_service
 monkeypatch.setattr(multiplier_service,'save_report_based_multiplier',lambda *args,**kwargs:None)
 monkeypatch.setattr(multiplier_service,'calculate_current_multipliers',lambda *args,**kwargs:None)
 with env() as db:
  r=report(db,revenue=1)
  staged=raw(fact(),fact('fin.net_income','3000000',identity='profit'))
  c=db.query(Company).one();a=planner.audit(db,c,staged,False)
  job=store.create(['TEST'],False,set())
  receipt=worker.apply_company(db,c,job,a,staged)
  assert receipt['added']==2
  assert r.revenue==Decimal('1.000') and r.net_income==Decimal('3.000')
  again=worker.apply_company(db,c,job,a,staged)
  assert again['recovered'] and again['added']==2
  assert db.query(FinancialReport).count()==1
  newjob=store.create(['TEST'],False,set())
  with pytest.raises(ValueError,match='изменились после аудита'):worker.apply_company(db,c,newjob,a,staged)
  db.rollback()

def test_new_protection_between_audit_and_apply_is_rechecked(env,monkeypatch):
 with env() as db:
  staged=raw(fact());c=db.query(Company).one();a=planner.audit(db,c,staged,False)
  job=store.create(['TEST'],False,set())
  monkeypatch.setattr(planner,'protected_tickers',lambda db:{'TEST'})
  with pytest.raises(ValueError,match='Защита изменилась'):worker.apply_company(db,c,job,a,staged)
  db.rollback();assert db.query(FinancialReport).count()==0

def test_resume_recovers_orphan_and_no_double_worker(env):
 job=store.create(['TEST'],False,set());store.update(job['id'],status='running')
 store.item_update(job['id'],'TEST',status='running')
 worker.recover()
 assert store.get(job['id'])['status']=='paused'
 assert store.items(job['id'])[0]['status']=='pending'
 handle=worker.acquire();assert handle is not None
 try:
  assert worker.alive()
  with pytest.raises(ValueError,match='работает другая'):worker.start(job['id'])
 finally:handle.close()

def test_full_worker_audit_then_apply_with_backup(env,monkeypatch):
 from app.services.admin import backup_service
 from app.services.analysis import multiplier_service
 monkeypatch.setattr(multiplier_service,'save_report_based_multiplier',lambda *args,**kwargs:None)
 monkeypatch.setattr(multiplier_service,'calculate_current_multipliers',lambda *args,**kwargs:None)
 monkeypatch.setattr(source,'local',lambda ticker:raw(fact()))
 backups=[]
 monkeypatch.setattr(backup_service,'create_postgres_backup',lambda:backups.append('backup') or {'filename':'test.dump'})
 job=store.create(['TEST'],False,set());store.update(job['id'],status='running')
 worker.run(job['id'],worker.acquire())
 assert store.get(job['id'])['status']=='ready'
 assert store.items(job['id'])[0]['summary']['add']==1
 store.update(job['id'],status='running',phase='apply')
 worker.run(job['id'],worker.acquire())
 assert store.get(job['id'])['status']=='completed' and backups==['backup']
 assert store.items(job['id'])[0]['status']=='done'
 with env() as db:assert db.query(FinancialReport).one().revenue==Decimal('2.000')

def test_rate_limit_preserves_resume_and_failure_stops_writes(env,monkeypatch):
 monkeypatch.setattr(source,'fetch',lambda *a:(_ for _ in ()).throw(source.RateLimited(60)))
 job=store.create(['TEST'],True,set());store.update(job['id'],status='running')
 worker.run(job['id'],worker.acquire())
 assert store.get(job['id'])['status']=='paused' and store.get(job['id'])['retry_at']
 assert store.items(job['id'])[0]['status']=='pending'
 with pytest.raises(ValueError,match='пауза источника'):worker.start(job['id'])
 with env() as db:assert db.query(FinancialReport).count()==0

def test_routes_require_admin_and_csrf(env,monkeypatch):
 import app.utils.admin_guard as guard
 monkeypatch.setattr(guard,'SessionLocal',env)
 monkeypatch.setattr(guard,'current',lambda *args,**kwargs:None)
 app=FastAPI();app.include_router(router);app.add_middleware(guard.AdminGuardMiddleware)
 client=TestClient(app)
 assert client.get('/admin/dump-import/jobs').status_code==401
 assert client.post('/admin/dump-import/jobs',json={'tickers':['TEST']}).status_code==403
 from types import SimpleNamespace
 monkeypatch.setattr(guard,'current',lambda *args:(None,SimpleNamespace(id=1,role='user')))
 assert client.get('/admin/dump-import/jobs').status_code==403


def test_api_audit_pagination_and_path_validation(env,monkeypatch):
 app=FastAPI();app.include_router(router)
 def get_session():
  with env() as db:yield db
 app.dependency_overrides[get_db]=get_session
 client=TestClient(app)
 job=store.create(['TEST'],False,set())
 store.write(store.artifact(job['id'],'TEST','audit.json'),{'cells':[{'action':'difference'},{'action':'add'}],'warnings':[]})
 url='/admin/dump-import/jobs/'+job['id']+'/companies/TEST'
 data=client.get(url+'/cells?action=difference').json()
 assert data['total']==1 and len(data['items'])==1
 assert client.get('/admin/dump-import/jobs/unknown').status_code==404
 assert client.post('/admin/dump-import/jobs',json={'tickers':['../oops']}).status_code==422


def test_fetch_caches_all_variants_and_reuses_latest_local_snapshot(env,monkeypatch,tmp_path):
 calls=[]
 class Response:
  status_code=200
  def __init__(self,data):self.data=data
  def raise_for_status(self):pass
  def json(self):return {'result':{'structuredContent':self.data}}
 class FakeSession:
  headers={}
  def post(self,url,**kwargs):
   call=kwargs['json']['params'];calls.append(call['name'])
   if call['name']=='find_metrics':
    items=[{'code':'fin.revenue','variants':[{'ticker':'TEST','selector':'../../unsafe'}]}]
   else:items=[fact()]
   return Response({'dataset':{'version':'test-v1'},'status':'ok','items':items,'page':{'next_cursor':None}})
 monkeypatch.setattr(source.requests,'Session',FakeSession)
 monkeypatch.setattr(source.time,'sleep',lambda _:None)
 folder=tmp_path/'download'
 data=source.fetch('TEST',folder,lambda _:None,lambda:None)
 assert len(data['facts'])==1 and calls.count('get_series')==1
 assert len(list(folder.glob('*.json')))==12  # 10 queries + one series + final source
 assert source.local('TEST')['version']=='test-v1'
 previous=len(calls)
 source.fetch('TEST',folder,lambda _:None,lambda:None)
 assert len(calls)==previous


def test_multiplier_failure_rolls_back_reports_and_receipts(env,monkeypatch):
 from app.services.analysis import multiplier_service
 def fail(*args,**kwargs):raise RuntimeError('Calculation failed')
 monkeypatch.setattr(multiplier_service,'calculate_current_multipliers',fail)
 with env() as db:
  c=db.query(Company).one();staged=raw(fact());a=planner.audit(db,c,staged,False)
  job=store.create(['TEST'],False,set())
  with pytest.raises(RuntimeError,match='Calculation failed'):worker.apply_company(db,c,job,a,staged)
  db.rollback()
  assert db.query(FinancialReport).count()==0


def test_backup_failure_prevents_writes(env,monkeypatch):
 from app.services.admin import backup_service
 monkeypatch.setattr(source,'local',lambda _:raw(fact()))
 job=store.create(['TEST'],False,set());store.update(job['id'],status='running')
 worker.run(job['id'],worker.acquire())
 def fail():raise RuntimeError('Backup failed')
 monkeypatch.setattr(backup_service,'create_postgres_backup',fail)
 store.update(job['id'],status='running',phase='apply')
 worker.run(job['id'],worker.acquire())
 assert store.get(job['id'])['status']=='failed'
 with env() as db:assert db.query(FinancialReport).count()==0


def test_capex_apm_and_coverage_distinguish_missing_from_different_units(env):
 with env() as db:
  capex=fact('fin.capex','-5000000',identity='capex');capex['accounting_basis']='APM'
  revenue=fact();revenue['currency']='USD'
  staged=raw(capex,revenue)
  a=planner.audit(db,db.query(Company).one(),staged,False)
  cell=next(c for c in a['cells'] if c['field']=='capex')
  assert cell['source']=='5.000' and cell['action']=='add'
  coverage=next(c for c in a['coverage'] if c['field']=='revenue')
  assert coverage['present'] and coverage['facts']==1 and coverage['usable_facts']==0
  assert len(staged['facts'])==2

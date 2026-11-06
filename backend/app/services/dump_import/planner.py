from __future__ import annotations
import hashlib,json
from dataclasses import asdict
from types import SimpleNamespace
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from app.config import settings
from app.database import engine
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.enums import PeriodType,AccountingStandard
from app.services.analysis.market_snapshot import trustworthy_tickers
from app.services.analysis.vrednyj_synergy import CODES,build_plan

POLICY_VERSION=1
MATRIX_FIELDS=['shares_issued','shares_outstanding','shares_weighted_avg','treasury_shares','revenue','net_income','operating_profit','finance_costs','net_income_reported','total_assets','current_assets','goodwill','intangible_assets','cash_and_equivalents','debt','total_liabilities','current_liabilities','equity','non_controlling_interest','dividends_per_share','preferred_share_dividends','operating_cash_flow','capex','lease_principal','lease_interest','interest_paid','debt_principal','interest_received','cash_investments','depreciation_amortization']
FROZEN=set(json.loads(Path(__file__).with_name('protected_tickers.json').read_text()))

def apply_allowed():
 return (settings.DEBUG and engine.url.host in {'localhost','127.0.0.1'} and settings.POSTGRES_HOST in {'localhost','127.0.0.1'}
         and engine.url.database==settings.POSTGRES_DB and engine.url.username==settings.POSTGRES_USER
         and (engine.url.port or 5432)==settings.POSTGRES_PORT)

def company_kind(company):return str(company.company_type).lower().split('.')[-1]

def protected_tickers(db):return FROZEN|set(trustworthy_tickers(db))

def snapshot(rows):
 return [{col.name:str(getattr(r,col.name)) if getattr(r,col.name) is not None else None for col in FinancialReport.__table__.columns} for r in sorted(rows,key=lambda r:r.id)]

def fingerprint(rows):return hashlib.sha256(json.dumps(snapshot(rows),sort_keys=True).encode()).hexdigest()

def field_mapping(kind):
 mapping={key:list(value) for key,value in CODES.items()}
 if kind in {'lender','exchange'}:
  for key in ['current_assets','current_liabilities','debt','finance_costs']:mapping.pop(key,None)
  mapping['revenue']=[('bank.operating_income_after_credit_losses',0)] if kind=='lender' else [('fin.revenue',0)]
 mapping.update({
  'non_controlling_interest':[('fin.non_controlling_interest',0)],
  'goodwill':[('fin.goodwill',0)],'intangible_assets':[('fin.intangible_assets',0)],
  'interest_income':[('fin.interest_income',0)],'interest_received':[('fin.interest_received',0)],
  'lease_principal':[('fin.lease_principal',0)],'lease_interest':[('fin.lease_interest',0)],
  'interest_paid':[('fin.interest_paid',0)],'debt_principal':[('fin.debt_principal',0)],
 })
 if kind in {'lender','hybrid','exchange'}:
  mapping.update({'net_interest_income':[('bank.net_interest_income',0)],
   'fee_commission_income':[('bank.net_fee_commission_income',0)],
   'gross_loans':[('bank.gross_loans',0)],'loan_loss_allowance':[('bank.loan_loss_allowance',0)],
   'customer_deposits':[('bank.customer_deposits',0)],'interest_income':[('bank.interest_income',0)]})
 return mapping

def allowed_report(company,protected,existing,period_type):
 if company_kind(company)=='holding':return False,'Холдинги исключены владельцем'
 if existing and existing.verified_by_analyst:return False,'Отчёт проверен аналитиком'
 if protected:
  if existing:return False,'Существующий отчёт защищённой компании'
  if period_type=='annual':return False,'Новый годовой отчёт защищённой компании запрещён'
 return True,''

def audit(db,company,source,protected):
 rows=db.query(FinancialReport).filter_by(company_id=company.id).all()
 kind=company_kind(company);mapping=field_mapping(kind)
 staged=source['facts'];eligible=[];not_projected=Counter();issues=[]
 for f in staged:
  if f.get('ticker')!=company.ticker:raise ValueError('Источник вернул факт другой компании')
  bases={'IFRS','APM'} if f.get('metric_code')=='fin.capex' else {'IFRS'}
  if f.get('accounting_basis') not in bases or f.get('consolidation_scope')!='consolidated':
   not_projected['Другой стандарт или периметр']+=1;continue
  dims=f.get('dimensions') or {}
  if any(dims.get(k,v) not in accepted for k,v,accepted in [('business_segment','all',{'all','group'}),('geography','group',{'all','group'})]):
   not_projected['Сегментные значения сохранены отдельно']+=1;continue
  if (f.get('currency')!='RUB' and not (f.get('unit') in {'share','shares'} and f.get('currency') is None)) or f.get('unit') not in {'currency','RUB','share','shares'}:
   not_projected['Другая единица или валюта (включая EPS)']+=1;continue
  eligible.append(f)
 plan=build_plan(eligible,mapping)
 for f in staged:
  if f.get('has_source_conflict'):issues.append({'kind':'source_conflict','fact_id':f['id'],'metric':f['metric_code']})
 # All variations are retained, but only one value can occupy a report column.
 buckets={}
 for f in eligible:
  key=(f['metric_code'],f['period'].get('start'),f['period']['end'])
  buckets.setdefault(key,[]).append(f)
 for key,variants in buckets.items():
  values=[Decimal(f['value']) for f in variants]
  if max(values)-min(values)>Decimal(1000):issues.append({'kind':'alternatives','metric':key[0],'period':key[2],'facts':[f['id'] for f in variants]})
 lookup={(str(r.report_date),str(r.period_type).split('.')[-1].lower()):r for r in rows if r.accounting_standard==AccountingStandard.IFRS and r.consolidated}
 cells=[];report_plan=[]
 for item in plan['reports']:
  day=date.fromisoformat(item['report_date']);quarter=day.month//3
  period='annual' if quarter==4 else 'semi_annual' if quarter==2 else 'quarterly'
  r=lookup.get((item['report_date'],period))
  allowed,reason=allowed_report(company,protected,r,period)
  if r and r.currency!='RUB':allowed=False;reason='Валюта существующего отчёта отличается от RUB'
  additions={}
  for field,value in item['fields'].items():
   if field in {'capex','finance_costs','lease_principal','lease_interest','interest_paid','debt_principal'}:value=str(abs(Decimal(value)))
   old=getattr(r,field) if r else None
   if not allowed:action='blocked'
   elif company.ticker=='LKOH' and field in {'net_income','net_income_reported'}:action='blocked';reason='Прибыль ЛУКОЙЛа сохраняется по правилу владельца'
   elif old is None:action='add';additions[field]=value
   elif Decimal(str(old))==Decimal(str(value)):action='match'
   else:action='difference'
   cells.append({'date':item['report_date'],'period_type':period,'field':field,'current':str(old) if old is not None else None,
    'source':str(value),'action':action,'reason':reason if action=='blocked' else '',
    'delta':str(Decimal(str(value))-Decimal(str(old))) if old is not None else None,
    'definition':item['definitions'][field],'provenance':item['provenance'][field]})
  # Do not create empty report shells containing nothing but raw metadata.
  if additions:report_plan.append({'date':item['report_date'],'period_type':period,'report_id':r.id if r else None,
   'fields':additions,'provenance':{k:item['provenance'][k] for k in additions},'definitions':{k:item['definitions'][k] for k in additions}})
 all_codes={f['metric_code'] for f in staged};mapped_codes={c for choices in mapping.values() for c,_ in choices}
 coverage=[]
 expected=list(dict.fromkeys(MATRIX_FIELDS+(list(mapping) if kind in {'lender','hybrid','exchange'} else [])))
 if kind in {'lender','exchange'}:expected=[f for f in expected if f not in {'current_assets','current_liabilities','finance_costs','lease_principal','lease_interest','interest_paid','debt_principal','interest_received','cash_investments','depreciation_amortization'}]
 for field in expected:
  choices=mapping.get('net_income',[]) if field=='net_income_reported' else mapping.get(field,[(f'fin.{field}',0)])
  codes={c for c,_ in choices}
  coverage.append({'field':field,'codes':[c for c,_ in choices],'facts':sum(f['metric_code'] in codes for f in staged),
                   'present':bool(all_codes&codes),'usable_facts':sum(f['metric_code'] in codes for f in eligible),'mapped':field in mapping or field=='net_income_reported'})
 warnings=['Непустые поля сохраняются. Все факты остаются в архиве, включая не перенесённые в столбцы.',
           'Наличие совпадающих чисел не подтверждает владельческую семантику или нормализацию прибыли.']
 if any(c['definition'] in ['fin.net_income','fin.total_equity'] for c in cells):warnings.append('Используются прибыль/капитал группы как непроверенные значения; они могут отличаться от владельческих.')
 if source.get('truncated_metrics'):warnings.append('Источник обрезал варианты части метрик; полнота не подтверждена.')
 if not staged:warnings.append('В локальном снимке нет фактов. Это не доказывает отсутствие данных в MCP; выполните загрузку.')
 if company.ticker=='FIXR':
  # The earlier FIXR pilot has issuer-specific leases and attribution; common mapping is not a substitute.
  warnings.append('FIXR: общий debt может не включать аренду. Долг добавляется только после отдельного разбора методики.')
  for item in report_plan:item['fields'].pop('debt',None);item['provenance'].pop('debt',None);item['definitions'].pop('debt',None)
  report_plan=[item for item in report_plan if item['fields']]
  for cell in cells:
   if cell['field']=='debt' and cell['action']=='add':cell.update(action='blocked',reason='FIXR: требуется долг с обеими частями аренды')
 summary={'facts':len(staged),'metrics':len(all_codes),'periods':len({f['period']['end'] for f in staged}),
  'add':sum(c['action']=='add' for c in cells),'matches':sum(c['action']=='match' for c in cells),'differences':sum(c['action']=='difference' for c in cells),
  'blocked':sum(c['action']=='blocked' for c in cells),'new_reports':sum(r['report_id'] is None for r in report_plan),
  'missing_fields':sum(not c['present'] for c in coverage),'protected':protected,'first_date':min((f['period']['end'] for f in staged),default=None),
  'last_date':max((f['period']['end'] for f in staged),default=None)}
 from app.services.analysis.data_audit import audit_company
 annual=[r for r in rows if r.period_type==PeriodType.ANNUAL and r.accounting_standard==AccountingStandard.IFRS and r.consolidated]
 projected={str(r.report_date):SimpleNamespace(**{col.name:getattr(r,col.name) for col in FinancialReport.__table__.columns}) for r in annual}
 for item in report_plan:
  if item['period_type']!='annual':continue
  r=projected.get(item['date'])
  if r is None:
   r=SimpleNamespace(**{col.name:None for col in FinancialReport.__table__.columns})
   r.report_date=date.fromisoformat(item['date']);r.fiscal_year=r.report_date.year;r.currency='RUB';r.report_type='bank' if kind=='lender' else 'general';r.period_type=PeriodType.ANNUAL;r.accounting_standard=AccountingStandard.IFRS
   projected[item['date']]=r
  for key,value in item['fields'].items():setattr(r,key,Decimal(str(value)))
 return {'audit_before':asdict(audit_company(company,annual)),'audit_projected':asdict(audit_company(company,list(projected.values()))),'ticker':company.ticker,'company_id':company.id,'policy_version':POLICY_VERSION,'baseline':fingerprint(rows),
  'source_version':source.get('version'),'source_origin':source.get('origin'),'source_completeness':source.get('completeness'),
  'before':snapshot(rows),'summary':summary,'cells':cells,'reports':report_plan,'coverage':coverage,
  'unmapped_metrics':sorted(all_codes-mapped_codes),'not_projected':dict(not_projected),'issues':issues,'warnings':warnings}

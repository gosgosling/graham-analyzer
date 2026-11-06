"""Owner-authorized exhaustive VSEH experiment, local dev only; not a general importer.

All source facts are retained in extraction_notes, including unmapped metrics,
standalone quarters, alternative values and original definitions. Report columns
use deterministic source selection and YTD flows. Group NI/equity are explicitly
allowed for this unverified experiment, not certified as owners' amounts.
"""
import json
from collections import defaultdict, Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from app.database import SessionLocal, engine
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.stock_price import StockPrice
from app.models.enums import PeriodType, AccountingStandard, ReportSource

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'data/external/vrednyj-investor/2026-11-01/vseh-pilot'
MAP={
 'fin.revenue':'revenue', 'fin.net_income':'net_income',
 'fin.operating_profit':'operating_profit','fin.total_assets':'total_assets',
 'fin.total_liabilities':'total_liabilities','fin.total_current_assets':'current_assets',
 'fin.total_current_liabilities':'current_liabilities','fin.total_equity':'equity',
 'fin.cash_and_equivalents':'cash_and_equivalents','fin.interest_bearing_debt':'debt',
 'fin.operating_cash_flow':'operating_cash_flow','fin.capex':'capex',
 'fin.interest_expense':'finance_costs','fin.interest_income':'interest_income',
 'fin.depreciation_amortization':'depreciation_amortization',
 'fin.weighted_average_shares':'shares_weighted_avg',
}

def source_rank(f):
 review=f.get('review_status','')
 return (3 if review=='reviewed_owner_approved' else 2 if review.startswith('reviewed') else 1 if review=='machine_validated' else 0,
         f.get('status')=='canonical',f.get('updated_at',''),f['id'])

def normalized(f):
 # Prefer the printed figure times its explicit scale: avoids binary float tails.
 if f.get('reported_value') is not None and f.get('scale_multiplier') is not None:
  return Decimal(f['reported_value'])*Decimal(f['scale_multiplier'])
 return Decimal(f['value'])

def build_plan(facts):
 buckets=defaultdict(list)
 for f in facts:
  p=f['period'];buckets[(f['metric_code'],None if p['kind']=='instant' else p['start'],p['end'])].append(f)
 selected={k:max(v,key=source_rank) for k,v in buckets.items()}
 ends=sorted({f['period']['end'] for f in facts})
 reports=[]
 for end in ends:
  day=date.fromisoformat(end)
  if (day.month,day.day) not in {(3,31),(6,30),(9,30),(12,31)}:continue
  fields={};provenance={}
  for code,field in MAP.items():
   chosen=selected.get((code,None,end))
   if chosen is not None: sources=[chosen]
   else:
    chosen=selected.get((code,f'{day.year}-01-01',end))
    sources=[chosen] if chosen else []
    if not sources:
     cursor=date(day.year,1,1)
     while cursor<=day:
      options=[(k,f) for k,f in selected.items() if k[0]==code and k[1]==cursor.isoformat() and k[2]<=end]
      if not options:break
      k,f=max(options,key=lambda pair:pair[0][2]);sources.append(f);cursor=date.fromisoformat(k[2])+timedelta(days=1)
     if cursor!=day+timedelta(days=1):sources=[]
   if not sources:continue
   value=sum(normalized(f) for f in sources)
   if field=='shares_weighted_avg':value=int(value)
   else:value=str((value/Decimal(1000000)).quantize(Decimal('.001')))
   fields[field]=value;provenance[field]=[f['id'] for f in sources]
  if 'net_income' in fields:
   fields['net_income_reported']=fields['net_income'];provenance['net_income_reported']=provenance['net_income']
  reports.append({'report_date':end,'fields':fields,'provenance':provenance,
   'source_facts':[f for f in facts if f['period']['end']==end]})
 return reports

def main():
 assert engine.url.host in {'localhost','127.0.0.1'},'Only local dev is authorized'
 facts=json.loads((FOLDER/'all-facts.json').read_text())
 assert facts and all(f['ticker']=='VSEH' for f in facts)
 plan=build_plan(facts)
 dates=json.loads((ROOT/'tools/edisclosure-scraper/disclosure_dates.json').read_text()).get('VSEH',{})
 with SessionLocal() as db:
  c=db.query(Company).filter_by(ticker='VSEH').one()
  from app.services.analysis.market_snapshot import trustworthy_tickers
  frozen=json.loads((FOLDER.parent/'dev-before-import.json').read_text())['protected_tickers']
  assert c.ticker not in frozen and c.ticker not in set(trustworthy_tickers(db))
  assert str(c.company_type).lower().split('.')[-1]=='industrial'
  def snapshot(r):return {col.name:str(getattr(r,col.name)) for col in FinancialReport.__table__.columns}
  before={r.id:snapshot(r) for r in db.query(FinancialReport)}
  (FOLDER/'before-full-import.json').write_text(json.dumps(before,ensure_ascii=False))
  created=[];changes=[]
  for item in plan:
   day=date.fromisoformat(item['report_date']);q=day.month//3
   period=PeriodType.ANNUAL if q==4 else PeriodType.SEMI_ANNUAL if q==2 else PeriodType.QUARTERLY
   r=db.query(FinancialReport).filter_by(company_id=c.id,report_date=day,period_type=period,accounting_standard=AccountingStandard.IFRS,consolidated=True).one_or_none()
   if r is None:
    r=FinancialReport(company_id=c.id,report_date=day,fiscal_year=day.year,fiscal_quarter=q if q in {1,3} else None,
     period_type=period,accounting_standard=AccountingStandard.IFRS,consolidated=True,currency='RUB',exchange_rate=1,
     source=ReportSource.API,report_type='general',verified_by_analyst=False,auto_extracted=True,dividends_paid=None)
    db.add(r);db.flush();created.append(r.id)
   for field,value in item['fields'].items():
    old=getattr(r,field)
    if old is None or Decimal(str(old))!=Decimal(str(value)):
     changes.append({'report_date':str(day),'field':field,'before':str(old),'after':str(value)});setattr(r,field,value)
   if r.price_per_share is None:
    price=db.query(StockPrice).filter(StockPrice.company_id==c.id,StockPrice.date<=day,StockPrice.date>=day-timedelta(days=10)).order_by(StockPrice.date.desc()).first()
    if price:r.price_per_share=price.price
   published=dates.get(str(day.year)+('_H1' if q==2 else '')) if q in {2,4} else None
   if published and not r.disclosed_at and date.fromisoformat(published)>day:r.disclosed_at=date.fromisoformat(published)
   r.extraction_notes=json.dumps({'provider':'Data Foundry','experiment':'VSEH exhaustive owner-authorized dev test',
    'warning':'Group net income and group equity imported as-is for coverage test; not certified owners figures. Alternatives retained below.',
    'selection':'reviewed_owner_approved > reviewed > machine_validated; canonical then latest updated_at and fact id',
    'provenance':item['provenance'],'all_source_facts':item['source_facts'],'previous_notes':r.extraction_notes or ''},ensure_ascii=False)
   r.verified_by_analyst=False;r.auto_extracted=True;r.extraction_model='Data Foundry exhaustive VSEH dev experiment'
  db.flush()
  for r in db.query(FinancialReport).filter(FinancialReport.company_id!=c.id):assert snapshot(r)==before[r.id]
  db.commit()
  company_id=c.id
  rows=db.query(FinancialReport).filter_by(company_id=company_id).all()
  from app.services.analysis.multiplier_service import save_report_based_multiplier,calculate_current_multipliers,save_current_multiplier
  for r in rows:save_report_based_multiplier(db,r)
  m=calculate_current_multipliers(db,company_id)
  if m:save_current_multiplier(db,company_id,m)
  db.commit()
  result={'company_id':company_id,'reports':len(rows),'created':created,'changes':changes,'source_facts':len(facts),
    'source_metrics':dict(Counter(f['metric_code'] for f in facts)),
    'unmapped_metrics':sorted({f['metric_code'] for f in facts}-set(MAP)),
    'populated':{field:sum(getattr(r,field) is not None for r in rows) for field in sorted(set(MAP.values())|{'net_income_reported'})},
    'other_reports_unchanged':sum(1 for rid,cols in before.items() if int(cols['company_id'])!=company_id)}
 (FOLDER/'full-import-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
 (FOLDER/'full-import-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k!='changes'},ensure_ascii=False))
 print('changed cells',len(changes))

if __name__=='__main__':main()

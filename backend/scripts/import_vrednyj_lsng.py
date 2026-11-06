"""Dev-only LSNG synergy: preserve every existing populated Qwen field and every source fact."""
import argparse,json
from collections import Counter
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
from app.database import SessionLocal,engine
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.stock_price import StockPrice
from app.models.enums import PeriodType,AccountingStandard,ReportSource
from app.services.analysis.vrednyj_synergy import build_plan,CODES
ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'data/external/vrednyj-investor/2026-11-02/lsng-pilot'

def main(apply=False):
 assert engine.url.host in {'localhost','127.0.0.1'},'Local dev only'
 facts=json.loads((FOLDER/'all-facts.json').read_text());assert facts and all(f['ticker']=='LSNG' for f in facts)
 plan=build_plan(facts);(FOLDER/'synergy-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
 comparisons=[];added=[];created=[]
 with SessionLocal() as db:
  c=db.query(Company).filter_by(ticker='LSNG').one();assert c.id==64
  from app.services.analysis.market_snapshot import trustworthy_tickers
  frozen=json.loads((FOLDER.parent.parent/'2026-11-01/dev-before-import.json').read_text())['protected_tickers']
  assert c.ticker not in frozen and c.ticker not in set(trustworthy_tickers(db))
  def snapshot(r):return {col.name:str(getattr(r,col.name)) if getattr(r,col.name) is not None else None for col in FinancialReport.__table__.columns}
  all_before={r.id:snapshot(r) for r in db.query(FinancialReport)}
  if apply:
   assert not (FOLDER/'synergy-import-result.json').exists(),'One-shot experiment; do not overwrite its journal'
   (FOLDER/'all-reports-before.json').write_text(json.dumps(all_before,ensure_ascii=False))
  dates=json.loads((ROOT/'tools/edisclosure-scraper/disclosure_dates.json').read_text()).get('LSNG',{})
  for item in plan['reports']:
   day=date.fromisoformat(item['report_date']);q=day.month//3
   period=PeriodType.ANNUAL if q==4 else PeriodType.SEMI_ANNUAL if q==2 else PeriodType.QUARTERLY
   r=db.query(FinancialReport).filter_by(company_id=c.id,report_date=day,period_type=period,accounting_standard=AccountingStandard.IFRS,consolidated=True).one_or_none()
   is_new=r is None
   for field,value in item['fields'].items():
    old=getattr(r,field) if r else None
    difference=None if old is None else Decimal(value)-Decimal(str(old))
    comparisons.append({'report_date':str(day),'field':field,'qwen_before':str(old) if old is not None else None,
     'dump':str(value),'delta':str(difference) if difference is not None else None,
     'relative_pct':str(abs(difference/Decimal(str(old))*100).quantize(Decimal('.01'))) if old not in [None,0] else None,
     'status':'add' if old is None else 'match' if difference==0 else 'difference_preserved_qwen',
     'definition':item['definitions'][field],'provenance':item['provenance'][field]})
   if not apply:continue
   if r is None:
    r=FinancialReport(company_id=c.id,report_date=day,fiscal_year=day.year,fiscal_quarter=q if q in [1,3] else None,
     period_type=period,accounting_standard=AccountingStandard.IFRS,consolidated=True,currency='RUB',exchange_rate=1,
     source=ReportSource.API,report_type='general',verified_by_analyst=False,auto_extracted=True,dividends_paid=None)
    db.add(r);db.flush();created.append(r.id)
   provenance={}
   for field,value in item['fields'].items():
    if getattr(r,field) is None:
     setattr(r,field,value);provenance[field]=item['provenance'][field];added.append({'id':r.id,'report_date':str(day),'field':field,'value':str(value)})
   if r.price_per_share is None:
    price=db.query(StockPrice).filter(StockPrice.company_id==c.id,StockPrice.date<=day,StockPrice.date>=day-timedelta(days=10)).order_by(StockPrice.date.desc()).first()
    if price:r.price_per_share=price.price
   published=dates.get(str(day.year)+('_H1' if q==2 else '')) if q in [2,4] else None
   if published and not r.disclosed_at and date.fromisoformat(published)>day:r.disclosed_at=date.fromisoformat(published)
   r.extraction_notes=json.dumps({'experiment':'LSNG Qwen + Data Foundry dev synergy','policy':'Existing nonempty financial fields retained; all source alternatives kept. Group NI/equity are explicit experimental fallbacks, not certified owners figures.',
    'provenance_added':provenance,'dump_candidates':item['fields'],'definitions':item['definitions'],'all_source_facts':item['source_facts'],
    'other_date_facts':plan['other_date_facts'] if day==date.fromisoformat(plan['reports'][-1]['report_date']) else [],
    'previous_model':r.extraction_model,'previous_notes':r.extraction_notes or ''},ensure_ascii=False)
   r.extraction_model='Qwen + Data Foundry LSNG synergy';r.auto_extracted=True;r.verified_by_analyst=False
  (FOLDER/'comparison.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2))
  if not apply:
   print('PLAN',len(plan['reports']),dict(Counter(x['status'] for x in comparisons)));return
  db.flush()
  for r in db.query(FinancialReport):
   if r.company_id!=c.id:assert snapshot(r)==all_before[r.id]
   elif r.id in all_before:
    for field in set(CODES)|{'net_income_reported'}:
     if all_before[r.id][field] is not None:assert str(getattr(r,field))==all_before[r.id][field]
  db.commit()
  rows=db.query(FinancialReport).filter_by(company_id=c.id).order_by(FinancialReport.report_date).all()
  from app.services.analysis.multiplier_service import save_report_based_multiplier,calculate_current_multipliers,save_current_multiplier
  for r in rows:save_report_based_multiplier(db,r)
  mults=calculate_current_multipliers(db,c.id)
  if mults:save_current_multiplier(db,c.id,mults)
  db.commit()
  after=[snapshot(r) for r in rows];(FOLDER/'after-lsng.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
  result={'ticker':'LSNG','company_id':c.id,'reports_before':sum(x['company_id']==str(c.id) for x in all_before.values()),'reports_after':len(rows),
   'created':created,'added_cells':added,'comparison_counts':dict(Counter(x['status'] for x in comparisons)),
   'source_facts':len(facts),'source_metrics':dict(Counter(f['metric_code'] for f in facts)),
   'other_reports_unchanged':sum(x['company_id']!=str(c.id) for x in all_before.values()),'other_date_facts':len(plan['other_date_facts'])}
  (FOLDER/'synergy-import-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
  print(json.dumps({k:v for k,v in result.items() if k not in ['created','added_cells']},ensure_ascii=False));print('created',len(created),'added cells',len(added))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args();main(args.apply)

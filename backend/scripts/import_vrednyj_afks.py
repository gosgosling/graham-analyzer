"""Second dev pilot: AFKS only, fill NULL fields and add missing periods."""
import json
from datetime import date
from pathlib import Path
from app.database import SessionLocal,engine
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.enums import AccountingStandard,PeriodType,ReportSource
from app.services.analysis.vrednyj_import import MAPPING,build_reports

ROOT=Path(__file__).resolve().parents[2];FOLDER=ROOT/'data/external/vrednyj-investor/2026-11-01'

def main():
 raise RuntimeError('Holdings imports disabled by owner. Existing AFKS data must be preserved.')
 assert engine.url.host in {'localhost','127.0.0.1'}
 protected=set(json.loads((FOLDER/'dev-before-import.json').read_text())['protected_tickers'])
 assert 'AFKS' not in protected
 mapping={k:v for k,v in MAPPING.items() if k.startswith('fin.')}
 mapping.update({'afks.reported_pl_profit_attributable_parent':('net_income','flow'),
  'afks.reported_pl_depreciation_amortisation_expense':('depreciation_amortization','outflow')})
 plan=build_reports(json.loads((FOLDER/'afks-pilot/facts.json').read_text()),'AFKS',mapping)
 dates=json.loads((ROOT/'tools/edisclosure-scraper/disclosure_dates.json').read_text()).get('AFKS',{})
 created=[];filled=[];kept=0
 with SessionLocal() as db:
  company=db.query(Company).filter(Company.ticker=='AFKS').one()
  from app.services.analysis.market_snapshot import trustworthy_tickers
  if company.ticker in set(trustworthy_tickers(db)):
   raise RuntimeError('AFKS is now protected by the screener; pilot update refused')
  company_id=company.id
  before={r.id:{c.name:str(getattr(r,c.name)) for c in FinancialReport.__table__.columns} for r in db.query(FinancialReport) if r.company_id!=company.id}
  for item in plan['reports']:
   existing=db.query(FinancialReport).filter(FinancialReport.company_id==company.id,
    FinancialReport.report_date==date.fromisoformat(item['report_date']),FinancialReport.period_type==PeriodType(item['period_type']),
    FinancialReport.accounting_standard==AccountingStandard.IFRS,FinancialReport.consolidated==True).first()
   if existing and existing.currency!='RUB':continue
   r=existing
   if r is None:
    r=FinancialReport(company_id=company.id,report_date=date.fromisoformat(item['report_date']),fiscal_year=item['fiscal_year'],
     fiscal_quarter=item['fiscal_quarter'],period_type=PeriodType(item['period_type']),accounting_standard=AccountingStandard.IFRS,
     consolidated=True,currency='RUB',exchange_rate=1,source=ReportSource.API,report_type='general',
     verified_by_analyst=False,auto_extracted=True,dividends_paid=None,extraction_model='Data Foundry MCP pilot')
    db.add(r);db.flush();created.append(r.id)
   provenance={}
   for field,value in item['fields'].items():
    if getattr(r,field) is None:setattr(r,field,value);provenance[field]=item['provenance'].get(field,[]);filled.append({'id':r.id,'field':field})
    else:kept+=1
   key=str(r.fiscal_year)+('_H1' if item['period_type']=='semi_annual' else '')
   published=dates.get(key) if item['period_type']!='quarterly' else None
   if published and not r.disclosed_at and date.fromisoformat(published)>r.report_date:
    r.disclosed_at=date.fromisoformat(published)
   if provenance:
    old=r.extraction_notes or ''
    note={'provider':'Data Foundry','ticker':'AFKS','dataset_version':'20261101T004841Z-ece8a784','provenance':provenance,
      'previous_notes':old,'disclosure_source':'tools/edisclosure-scraper/disclosure_dates.json' if published else None}
    r.extraction_notes=json.dumps(note,ensure_ascii=False);r.verified_by_analyst=False;r.auto_extracted=True
  db.flush()
  for r in db.query(FinancialReport).filter(FinancialReport.company_id!=company.id):
   assert {c.name:str(getattr(r,c.name)) for c in FinancialReport.__table__.columns}==before[r.id]
  db.commit()
 result={'ticker':'AFKS','company_id':company_id,'created_report_ids':created,'filled_fields':filled,'kept_existing_values':kept,
  'other_reports_unchanged':len(before),'protected_companies':len(protected),'skipped':plan['skipped']}
 (FOLDER/'afks-pilot/import-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
 (FOLDER/'afks-pilot/import-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({'created':len(created),'filled':len(filled),'kept':kept,'other_reports_unchanged':len(before)}))

if __name__=='__main__':main()

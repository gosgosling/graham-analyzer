"""Apply one FIXR pilot to LOCAL DEV only; immutable baseline and policy checks."""
import argparse
import json
from datetime import date
from pathlib import Path
from app.database import SessionLocal, engine
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.enums import PeriodType, AccountingStandard, ReportSource
from app.services.analysis.vrednyj_import import build_reports, can_add_report

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'data/external/vrednyj-investor/2026-11-01'

def snapshot(db):
    return [{c.name:str(getattr(r,c.name)) for c in FinancialReport.__table__.columns}
        for r in db.query(FinancialReport).order_by(FinancialReport.id)]

def main(apply=False):
    if engine.url.host not in {'localhost','127.0.0.1'}:
        raise RuntimeError('Only local dev is allowed')
    inventory=json.loads((FOLDER/'dev-before-import.json').read_text())
    baseline=json.loads((FOLDER/'dev-reports-before.json').read_text())
    protected=set(inventory['protected_tickers'])
    plan=build_reports(json.loads((FOLDER/'fixr-pilot/facts.json').read_text()))
    (FOLDER/'fixr-pilot/import-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    with SessionLocal() as db:
        company=db.query(Company).filter(Company.ticker=='FIXR').one()
        existing=db.query(FinancialReport).filter(FinancialReport.company_id==company.id).count()
        if existing:raise RuntimeError('FIXR already has reports; refuse to overwrite or rerun blindly')
        if snapshot(db)!=baseline:raise RuntimeError('Existing dev reports changed since backup; inspect before proceeding')
        for report in plan['reports']:
            if not can_add_report(company.ticker in protected,report['period_type'],False):
                raise RuntimeError('Protected company policy rejects annual creation')
        if not apply:
            print(json.dumps({'dry_run':True,'ticker':'FIXR','new_reports':len(plan['reports']),'protected_companies':len(protected),'skipped':len(plan['skipped'])}));return
        ids=[]
        try:
            for report in plan['reports']:
                note={'provider':'Data Foundry','dataset_version':'20261101T004841Z-ece8a784',
                    'status':'pilot_unverified','provenance':report['provenance'],
                    'notes':['Only owner-attributable income/equity mapped; group totals left out.',
                             'Quarterly P&L assembled as YTD from compatible inputs.',
                             'Cash-flow interest paid already inside OCF; not deducted twice.',
                             'Publication date unknown; not invented.']}
                r=FinancialReport(company_id=company.id,report_date=date.fromisoformat(report['report_date']),
                    fiscal_year=report['fiscal_year'],fiscal_quarter=report['fiscal_quarter'],
                    period_type=PeriodType(report['period_type']),accounting_standard=AccountingStandard.IFRS,
                    consolidated=True,currency='RUB',exchange_rate=1,source=ReportSource.API,
                    report_type='general',verified_by_analyst=False,auto_extracted=True,
                    dividends_paid=None,extraction_model='Data Foundry MCP pilot',
                    extraction_notes=json.dumps(note,ensure_ascii=False),**report['fields'])
                db.add(r);db.flush();ids.append(r.id)
            before_ids={int(r['id']) for r in baseline}
            unchanged=[r for r in snapshot(db) if int(r['id']) in before_ids]
            if unchanged!=baseline:raise RuntimeError('An existing report changed; rollback')
            db.commit()
        except Exception:
            db.rollback();raise
        manifest={'ticker':'FIXR','company_id':company.id,'created_report_ids':ids,'protected_tickers':sorted(protected),
            'existing_reports_unchanged':True,'existing_reports_checked':len(baseline),'plan':'import-plan.json'}
        (FOLDER/'fixr-pilot/import-result.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        print(json.dumps({'created':len(ids),'existing_reports_checked':len(baseline),'existing_reports_unchanged':True}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true')
    main(parser.parse_args().apply)

"""Dev-only FIXR disclosure dates and actual report prices; proxy remains separate."""
import json
from datetime import date,timedelta
from pathlib import Path
from app.database import SessionLocal,engine
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.stock_price import StockPrice

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'data/external/vrednyj-investor/2026-11-01/fixr-pilot'
CAL='https://ir.fix-price.com/investors/investor_calendar/'
AR22='https://ar2022.fix-price.com/en/corporate-governance/shareholder-investor-engagement'
AR23='https://ar2023.fix-price.com/pdf/en/FP-ar23-full-en.pdf'
PROSPECTUS='https://ir.fix-price.com/upload/iblock/135/Fix%20Price%20Registration%20Document%2015%20Feb%202021.pdf'
DATES={
 '2018-12-31':('2021-02-15',PROSPECTUS),'2019-12-31':('2021-02-15',PROSPECTUS),'2020-12-31':('2021-02-15',PROSPECTUS),
 '2021-06-30':('2021-08-12','https://ir.fix-price.com/media?PAGEN_1=11&category=0'),
 '2021-09-30':('2021-10-27','https://ir.fix-price.com/media?PAGEN_1=11&category=0'),
 '2021-12-31':('2022-02-28',AR22),'2022-06-30':('2022-09-19',AR22),'2022-09-30':('2022-10-27',AR22),'2022-12-31':('2023-02-27',AR22),
 '2023-03-31':('2023-04-27',AR23),'2023-06-30':('2023-09-07',AR23),'2023-09-30':('2023-10-31',AR23),'2023-12-31':('2024-02-28',AR23),
 '2024-03-31':('2024-04-26',CAL),'2024-06-30':('2024-08-08',CAL),'2024-09-30':('2024-10-31',CAL),'2024-12-31':('2025-02-27',CAL),
 '2025-03-31':('2025-04-30',CAL),'2025-06-30':('2025-08-28',CAL),'2025-09-30':('2025-10-30',CAL),'2025-12-31':('2026-03-03',CAL),
 '2026-03-31':('2026-04-30','https://investors.fix-price.ru/upload/iblock/63d/nmxm6rvlv835otuetjycq0lcr7m5n0gy/PJSC_Fix_Price_announces_key_operating_and_financial_results_for_Q1_2026_RUS.pdf'),
 '2026-06-30':('2026-08-27',CAL),
}

def main():
 assert engine.url.host in {'localhost','127.0.0.1'}
 result={'dates':[],'unknown':[],'actual_prices':[]}
 with SessionLocal() as db:
  company=db.query(Company).filter(Company.ticker=='FIXR').one()
  for r in db.query(FinancialReport).filter(FinancialReport.company_id==company.id):
   key=r.report_date.isoformat();data=DATES.get(key)
   if data and not r.disclosed_at:
    published,source=data;r.disclosed_at=date.fromisoformat(published)
    if not r.filing_date:r.filing_date=r.disclosed_at
    note=json.loads(r.extraction_notes or '{}');note['disclosure']={'date':published,'url':source,'kind':'prospectus_known_availability' if key<'2021' else 'official_calendar_or_financial_release'}
    note['notes']=[x for x in note.get('notes',[]) if x!='Publication date unknown; not invented.']
    r.extraction_notes=json.dumps(note,ensure_ascii=False);result['dates'].append({'period':key,'date':published,'url':source})
   elif not data:result['unknown'].append(key)
   # No FIXP/158 proxy is ever written into report prices or StockPrice.
   if not r.price_per_share:
    row=db.query(StockPrice).filter(StockPrice.company_id==company.id,StockPrice.date<=r.report_date,StockPrice.date>=r.report_date-timedelta(days=10)).order_by(StockPrice.date.desc()).first()
    if row:r.price_per_share=row.price;result['actual_prices'].append({'period':key,'price':str(row.price),'date':row.date.isoformat()})
  db.commit()
 (OUT/'history-enrichment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({'disclosure_dates':len(result['dates']),'unknown_dates':result['unknown'],'actual_report_prices':len(result['actual_prices'])},ensure_ascii=False))

if __name__=='__main__':main()

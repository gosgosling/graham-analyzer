"""Lossless staging + fill-only comparison for one explicitly selected dev company."""
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal

# Lower number means a more specific match to the project's column definition.
CODES={
 'revenue':[('fin.revenue',0)],
 'net_income':[('fin.profit_attributable_to_owners',0),('fin.net_income',1)],
 'operating_profit':[('fin.operating_profit',0)],
 'total_assets':[('fin.total_assets',0)],'total_liabilities':[('fin.total_liabilities',0)],
 'current_assets':[('fin.total_current_assets',0)],'current_liabilities':[('fin.total_current_liabilities',0)],
 'equity':[('fin.equity_attributable_to_owners',0),('fin.total_equity',1)],
 'cash_and_equivalents':[('fin.cash_and_equivalents',0)],
 'debt':[('fin.interest_bearing_debt',0)],'operating_cash_flow':[('fin.operating_cash_flow',0)],
 'capex':[('fin.capex',0)],'finance_costs':[('fin.interest_expense',0)],
 'depreciation_amortization':[('fin.depreciation_amortization',0)],
 'shares_weighted_avg':[('fin.weighted_average_shares',0)],
}

def normalized(fact):
 if fact.get('reported_value') is not None and fact.get('scale_multiplier') is not None:
  return Decimal(fact['reported_value'])*Decimal(fact['scale_multiplier'])
 return Decimal(fact['value'])

def rank(f):
 review=f.get('review_status','')
 return (3 if review=='reviewed_owner_approved' else 2 if review.startswith('reviewed') else 1 if review=='machine_validated' else 0,
         f.get('status')=='canonical',f.get('updated_at',''),f['id'])

def build_plan(facts, mapping=None):
 buckets=defaultdict(list)
 for f in facts:
  p=f['period'];buckets[(f['metric_code'],None if p['kind']=='instant' else p['start'],p['end'])].append(f)
 selected={key:max(group,key=rank) for key,group in buckets.items()}
 result=[];extras=[]
 ends=sorted({f['period']['end'] for f in facts})
 for end in ends:
  day=date.fromisoformat(end)
  if (day.month,day.day) not in {(3,31),(6,30),(9,30),(12,31)}:
   extras.extend(f for f in facts if f['period']['end']==end);continue
  fields={};provenance={};definitions={}
  for field,codes in (CODES if mapping is None else mapping).items():
   for code,priority in sorted(codes,key=lambda c:c[1]):
    direct=selected.get((code,None,end)) or selected.get((code,f'{day.year}-01-01',end))
    sources=[direct] if direct else []
    if not sources and field!='shares_weighted_avg':
     cursor=date(day.year,1,1)
     while cursor<=day:
      choices=[(k,f) for k,f in selected.items() if k[0]==code and k[1]==cursor.isoformat() and k[2]<=end]
      if not choices:break
      key,f=max(choices,key=lambda pair:pair[0][2]);sources.append(f);cursor=date.fromisoformat(key[2])+timedelta(days=1)
     if cursor!=day+timedelta(days=1):sources=[]
    if not sources:continue
    value=sum(normalized(f) for f in sources)
    fields[field]=int(value) if field=='shares_weighted_avg' else str((value/Decimal(1000000)).quantize(Decimal('.001')))
    provenance[field]=[f['id'] for f in sources];definitions[field]=code
    break
  if 'net_income' in fields:
   fields['net_income_reported']=fields['net_income'];provenance['net_income_reported']=provenance['net_income'];definitions['net_income_reported']=definitions['net_income']
  result.append({'report_date':end,'fields':fields,'provenance':provenance,'definitions':definitions,
   'source_facts':[f for f in facts if f['period']['end']==end]})
 assert sum(len(item['source_facts']) for item in result)+len(extras)==len(facts)
 return {'reports':result,'other_date_facts':extras}

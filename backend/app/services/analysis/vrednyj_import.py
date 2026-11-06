"""Conservative FIXR pilot: decimal units, owner figures, cumulative periods.

No network or database writes here. Every selected input retains provenance.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

MAPPING = {
    'fin.revenue': ('revenue','flow'),
    'fin.operating_profit': ('operating_profit','flow'),
    'fin.total_assets': ('total_assets','stock'),
    'fin.total_liabilities': ('total_liabilities','stock'),
    'fin.total_current_assets': ('current_assets','stock'),
    'fin.total_current_liabilities': ('current_liabilities','stock'),
    'fin.cash_and_equivalents': ('cash_and_equivalents','stock'),
    'fin.interest_bearing_debt': ('debt','stock'),
    'fixr.current_lease_liabilities': ('_lease_current','stock'),
    'fixr.noncurrent_lease_liabilities': ('_lease_noncurrent','stock'),
    'fin.operating_cash_flow': ('operating_cash_flow','flow'),
    'fin.capex': ('capex','outflow'),
    'fin.weighted_average_shares': ('shares_weighted_avg','shares'),
    'fixr.equity_attributable_to_shareholders': ('equity','stock'),
    'fixr.equity_attributable_to_nci': ('non_controlling_interest','stock'),
    'fixr.profit_attributable_to_shareholders': ('net_income','flow'),
    'fixr.goodwill': ('goodwill','stock'),
    'fixr.intangible_assets': ('intangible_assets','stock'),
    'fixr.interest_expense': ('finance_costs','outflow'),
    'fixr.interest_income': ('interest_income','flow'),
    'fixr.cf_depreciation_and_amortisation': ('depreciation_amortization','outflow'),
    'fixr.cf_lease_payments': ('lease_principal','outflow'),
    'fixr.cf_repayment_of_loans_and_borrowings': ('debt_principal','outflow'),
    'fixr.cf_interest_received': ('interest_received','flow'),
}


def can_add_report(protected, period_type, already_exists, company_type='industrial'):
    if str(company_type).lower().split('.')[-1]=='holding':
        return False
    return not already_exists and (not protected or period_type in {'quarterly','semi_annual'})


def build_reports(facts, ticker='FIXR', mapping=None):
    mapping = MAPPING if mapping is None else mapping
    buckets=defaultdict(list)
    skipped=[]
    for fact in facts:
        code=fact.get('metric_code')
        if fact.get('ticker')!=ticker or code not in mapping:
            continue
        field,kind=mapping[code]
        dims=fact.get('dimensions',{})
        if (fact.get('accounting_basis') not in ({'IFRS','APM'} if code=='fin.capex' else {'IFRS'})
            or fact.get('consolidation_scope')!='consolidated'
            or fact.get('status') not in {'canonical','computed'}
            or fact.get('has_source_conflict')
            or dims.get('geography','group') not in {'group','all'}
            or dims.get('business_segment','all') not in {'all','group'}):
            skipped.append({'id':fact['id'],'reason':'basis, scope, status, conflict or dimensions'});continue
        if kind=='shares':
            if fact.get('unit') not in {'share','shares'}:
                skipped.append({'id':fact['id'],'reason':'unsupported shares unit'});continue
            value=Decimal(fact['value'])
        else:
            if fact.get('currency')!='RUB' or fact.get('unit') not in {'currency','RUB'}:
                skipped.append({'id':fact['id'],'reason':'unsupported currency/unit'});continue
            value=Decimal(fact['value'])/Decimal(1000000)
        if kind=='stock' and field not in {'equity','non_controlling_interest'} and value<0:
            skipped.append({'id':fact['id'],'reason':'negative balance stock quarantined'});continue
        period=fact['period'];end=period['end']
        start=period.get('start') if kind!='stock' else None
        if kind!='stock' and not start:continue
        if kind=='stock' and period.get('kind')!='instant':
            skipped.append({'id':fact['id'],'reason':'stock is not an instant'});continue
        rank=(fact.get('review_status')=='reviewed',fact.get('methodology',{}).get('code','').startswith('fix_price'))
        buckets[(field,start,end,kind)].append((rank,value,fact))
    selected={}
    for key,variants in buckets.items():
        rank=max(v[0] for v in variants)
        chosen=[v for v in variants if v[0]==rank]
        if len({v[1] for v in chosen})!=1:
            skipped.append({'key':key,'reason':'different values at equal priority','ids':[v[2]['id'] for v in chosen]});continue
        _,value,fact=chosen[0]
        selected[key]=(value,[{'fact_id':v[2]['id'],'source_id':v[2]['source_id'],'methodology':v[2].get('methodology',{}).get('code'),'comparability_key':v[2].get('methodology',{}).get('comparability_key'),'review_status':v[2].get('review_status')} for v in chosen])
    ends=sorted({k[2] for k in selected})
    reports=[]
    for end in ends:
        day=date.fromisoformat(end)
        if (day.month,day.day) not in {(3,31),(6,30),(9,30),(12,31)}:continue
        start=f'{day.year}-01-01';quarter=day.month//3
        fields={};provenance={}
        for field,kind in set(mapping.values()):
            result=selected.get((field,None,end,kind)) if kind=='stock' else selected.get((field,start,end,kind))
            if result is None and kind not in {'stock','shares'}:
                # Exact tiling, never sum standalone Q2 with a cumulative H1.
                cursor=date(day.year,1,1);total=Decimal(0);sources=[]
                while cursor<=day:
                    choices=[(k,v) for k,v in selected.items() if k[0]==field and k[1]==cursor.isoformat() and k[3]==kind and k[2]<=end]
                    if not choices:break
                    k,v=max(choices,key=lambda x:x[0][2])
                    total+=v[0];sources+=v[1];cursor=date.fromisoformat(k[2])+timedelta(days=1)
                signatures={s['comparability_key'] or s['methodology'] for s in sources}
                if cursor==day+timedelta(days=1) and len(signatures)==1:result=(total,sources)
            if result is None:continue
            value,sources=result
            if kind=='outflow':value=abs(value)
            if kind=='shares':
                if value!=value.to_integral_value() or value<=0:continue
                fields[field]=int(value)
            else:fields[field]=str(value.quantize(Decimal('.001')))
            provenance[field]=sources
        if not any(k in fields for k in ('revenue','net_income','total_assets')):continue
        # This issuer's fin.interest_bearing_debt is loans only. Our debt
        # definition includes IFRS 16 leases (FIELD-MAPPING.md).
        if ticker=='FIXR' and 'debt' in fields:
            if all(k in fields for k in ('_lease_current','_lease_noncurrent')):
                fields['debt']=str(sum(Decimal(fields[k]) for k in ('debt','_lease_current','_lease_noncurrent')))
                provenance['debt']+=provenance['_lease_current']+provenance['_lease_noncurrent']
            else:
                fields.pop('debt');provenance.pop('debt')
                skipped.append({'end':end,'reason':'incomplete lease debt; debt left unknown'})
        for temporary in ('_lease_current','_lease_noncurrent'):
            fields.pop(temporary,None);provenance.pop(temporary,None)
        if 'net_income' in fields:
            fields['net_income_reported']=fields['net_income'];provenance['net_income_reported']=provenance['net_income']
        if ticker=='FIXR' and 'interest_received' in fields:
            # FIXR Databook: interest received B31 precedes OCF total B33.
            fields['interest_received_in_ocf']=True
        # Check balance only when every component is known; no invented NCI=0.
        if all(k in fields for k in ('total_assets','total_liabilities','equity','non_controlling_interest')):
            gap=abs(Decimal(fields['total_assets'])-sum(Decimal(fields[k]) for k in ('total_liabilities','equity','non_controlling_interest')))
            if gap>max(Decimal('1'),abs(Decimal(fields['total_assets']))*Decimal('.01')):
                skipped.append({'end':end,'reason':'balance discrepancy; stock fields quarantined'})
                for field,kind in set(mapping.values()):
                    if kind=='stock':fields.pop(field,None);provenance.pop(field,None)
        reports.append({'report_date':end,'fiscal_year':day.year,'period_type':'annual' if quarter==4 else 'semi_annual' if quarter==2 else 'quarterly','fiscal_quarter':None if quarter in {2,4} else quarter,'fields':fields,'provenance':provenance})
    return {'reports':reports,'skipped':skipped}

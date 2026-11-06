from app.services.analysis.vrednyj_import import build_reports, can_add_report

def fact(code,value,start,end,kind='duration',review='reviewed',identity='x',method='same'):
    return {'id':identity,'source_id':'src-'+identity,'ticker':'FIXR','metric_code':code,
        'value':str(value),'unit':'currency','currency':'RUB','accounting_basis':'IFRS',
        'consolidation_scope':'consolidated','status':'canonical','dimensions':{},
        'review_status':review,'methodology':{'code':method,'comparability_key':method},
        'period':{'kind':kind,'start':start,'end':end}}

def test_quarters_become_ytd_and_units_are_converted_once():
    rows=[fact('fin.revenue',100000000,'2025-01-01','2025-03-31',identity='q1'),
          fact('fin.revenue',200000000,'2025-04-01','2025-06-30',identity='q2')]
    reports=build_reports(rows)['reports']
    assert reports[-1]['fields']['revenue']=='300.000'
    assert reports[-1]['period_type']=='semi_annual'
    assert len(reports[-1]['provenance']['revenue'])==2

def test_group_profit_is_not_owner_profit_and_negative_cash_is_quarantined():
    rows=[fact('fin.revenue',1000000,'2025-01-01','2025-12-31'),
          fact('fin.net_income',900000,None,'2025-12-31'),
          fact('fin.cash_and_equivalents',-1000000,None,'2025-12-31','instant')]
    plan=build_reports(rows)
    assert 'net_income' not in plan['reports'][0]['fields']
    assert 'cash_and_equivalents' not in plan['reports'][0]['fields']
    assert plan['skipped'][0]['reason']=='negative balance stock quarantined'

def test_conflicting_values_do_not_overwrite_and_methods_are_not_mixed():
    rows=[fact('fin.revenue',1000000,'2025-01-01','2025-03-31',identity='a'),
          fact('fin.revenue',2000000,'2025-01-01','2025-03-31',identity='b')]
    assert build_reports(rows)['reports']==[]
    rows=[fact('fin.revenue',1000000,'2025-01-01','2025-03-31',identity='a',method='old'),
          fact('fin.revenue',2000000,'2025-04-01','2025-06-30',identity='b',method='new')]
    assert all(r['report_date']!='2025-06-30' for r in build_reports(rows)['reports'])

def test_protected_annuals_and_existing_interims_are_immutable():
    assert not can_add_report(False,'annual',False,'holding')
    assert not can_add_report(False,'quarterly',False,'holding')
    assert not can_add_report(True,'annual',False)
    assert can_add_report(True,'quarterly',False)
    assert can_add_report(True,'semi_annual',False)
    assert not can_add_report(True,'quarterly',True)
    assert not can_add_report(False,'annual',True)

def test_fixr_debt_includes_both_lease_components():
    rows=[fact('fin.total_assets',100000000,None,'2025-12-31','instant'),
          fact('fin.interest_bearing_debt',10000000,None,'2025-12-31','instant'),
          fact('fixr.current_lease_liabilities',2000000,None,'2025-12-31','instant'),
          fact('fixr.noncurrent_lease_liabilities',3000000,None,'2025-12-31','instant')]
    fields=build_reports(rows)['reports'][0]['fields']
    assert fields['debt']=='15.000'
    assert not any(k.startswith('_lease') for k in fields)
    assert 'debt' not in build_reports(rows[:-1])['reports'][0]['fields']

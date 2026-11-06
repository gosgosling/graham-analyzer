from app.services.analysis.vrednyj_synergy import build_plan


def fact(identity,code,value,start,end,review='machine_validated'):
    return {'id':identity,'ticker':'LSNG','metric_code':code,'value':str(value),'review_status':review,
            'status':'canonical','period':{'kind':'duration' if start else 'instant','start':start,'end':end}}


def test_owner_equity_precedes_total_and_all_alternatives_are_retained():
    rows=[fact('total','fin.total_equity',10000000,None,'2023-06-30','reviewed_primary_source'),
          fact('owner','fin.equity_attributable_to_owners',9000000,None,'2023-06-30'),
          fact('opening','fin.total_assets',20000000,None,'2023-01-01')]
    plan=build_plan(rows)
    assert plan['reports'][0]['fields']['equity']=='9.000'
    assert plan['reports'][0]['provenance']['equity']==['owner']
    assert plan['reports'][0]['source_facts']==rows[:2]
    assert plan['other_date_facts']==rows[2:]


def test_quarters_tile_ytd_but_standalone_q2_is_not_a_half_year():
    rows=[fact('q1','fin.revenue',1000000,'2025-01-01','2025-03-31'),
          fact('q2','fin.revenue',2000000,'2025-04-01','2025-06-30')]
    assert build_plan(rows)['reports'][-1]['fields']['revenue']=='3.000'
    partial=build_plan(rows[1:])['reports'][0]
    assert 'revenue' not in partial['fields']
    assert partial['source_facts']==rows[1:]


def test_tiny_float_differences_do_not_erase_a_field_and_losses_are_allowed():
    a=fact('a','fin.net_income','-2000000.000000001','2025-01-01','2025-12-31')
    b=fact('b','fin.net_income','-2000000','2025-01-01','2025-12-31','reviewed_owner_approved')
    b.update(reported_value='-2000',scale_multiplier='1000')
    plan=build_plan([a,b])['reports'][0]
    assert plan['fields']['net_income']=='-2.000'
    assert len(plan['source_facts'])==2

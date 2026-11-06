from scripts.import_vrednyj_vseh_full import build_plan


def fact(identity, code, value, start, end, review='machine_validated', printed=None, scale=None):
    return {'id':identity,'metric_code':code,'value':value,'review_status':review,
            'status':'canonical','period':{'kind':'duration' if start else 'instant','start':start,'end':end},
            'reported_value':printed,'scale_multiplier':scale}


def test_experiment_keeps_all_alternatives_and_uses_printed_value():
    rows=[fact('machine','fin.net_income','999000000','2025-01-01','2025-12-31'),
          fact('approved','fin.net_income','3367869999.999999','2025-01-01','2025-12-31',
               'reviewed_owner_approved','3367.870','1000000'),
          fact('eps','fin.eps_basic','6.74','2025-01-01','2025-12-31')]
    report=build_plan(rows)[0]
    assert report['fields']['net_income']=='3367.870'
    assert report['fields']['net_income_reported']=='3367.870'
    assert report['provenance']['net_income']==['approved']
    assert report['source_facts']==rows


def test_experiment_builds_ytd_without_dropping_group_equity_or_losses():
    rows=[fact('q1','fin.net_income','-2000000','2025-01-01','2025-03-31'),
          fact('q2','fin.net_income','1000000','2025-04-01','2025-06-30'),
          fact('equity','fin.total_equity','5000000',None,'2025-06-30')]
    report=build_plan(rows)[-1]
    assert report['fields']['net_income']=='-1.000'
    assert report['fields']['equity']=='5.000'
    assert sum(len(r['source_facts']) for r in build_plan(rows))==len(rows)

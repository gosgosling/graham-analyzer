"""MOEX assistance for the apply step, using the same helpers as the matrix.

Fetch before locking reports; apply the prepared values in the company transaction.
ISSUESIZE is a current registry value adjusted for known splits, not a historical
register of issuance. Keep that distinction in the field provenance.
"""
from datetime import date
from decimal import Decimal

from app.models.enums import AccountingStandard
from app.services.market.split_scale import traded_close_on_or_before
from app.services.share_splits import company_splits, shares_at_date
from app.services.ticker_history import resolve_ticker
from app.utils.moex_client import get_shares_outstanding
from . import planner, store


def prepare(db, company, rows, audit, protected):
    targets = []
    planned = {r['report_id']: r for r in audit['reports'] if r['report_id'] is not None}
    for row in rows:
        if row.accounting_standard != AccountingStandard.IFRS or not row.consolidated:
            continue
        period = row.period_type.value
        if not planner.allowed_report(company, protected, row, period)[0]:
            continue
        fields = dict(planned.get(row.id, {}).get('fields', {}))
        targets.append({
            'report_id': row.id, 'date': row.report_date.isoformat(), 'period_type': period,
            'filing_date': row.filing_date.isoformat() if row.filing_date else None,
            'currency': row.currency, 'exchange_rate': str(row.exchange_rate or ''),
            'missing': [f for f in ['price_per_share', 'price_at_filing', 'shares_issued']
                        if getattr(row, f) is None and f not in fields],
        })
    for row in audit['reports']:
        if row['report_id'] is None:
            targets.append({**row, 'currency': 'RUB', 'exchange_rate': '1', 'filing_date': None,
                            'missing': [f for f in ['price_per_share', 'shares_issued'] if f not in row['fields']]})
    return {'ticker': company.ticker, 'former_tickers': company.former_tickers,
            'splits': company_splits(db, company), 'targets': targets}


def fetch(plan, event, check):
    """No report writes or open DB transaction while waiting for MOEX."""
    result = {'reports': [], 'missing': [], 'fetched_at': store.now()}
    targets = plan['targets']
    ticker = plan['ticker']
    check()
    issue = get_shares_outstanding(ticker) if any('shares_issued' in t['missing'] for t in targets) else None
    size = issue.get('issuesize') if issue else None
    if size is not None and int(size) <= 0:
        size = None
    prices = {}
    for i, target in enumerate(targets):
        check()
        fields, provenance = {}, {}
        day = date.fromisoformat(target['date'])
        if 'shares_issued' in target['missing']:
            if size:
                fields['shares_issued'] = shares_at_date(int(size), plan['splits'], day)
                provenance['shares_issued'] = {
                    'source': 'MOEX ISSUESIZE', 'ticker': ticker, 'current_issuesize': int(size),
                    'retrieved_at': result['fetched_at'], 'report_date': target['date'],
                    'note': 'Текущий выпуск с поправкой на известные дробления; история допэмиссий не учитывается.',
                }
            else:
                result['missing'].append({'date': target['date'], 'field': 'shares_issued', 'reason': 'MOEX не вернул выпуск'})
        for field, requested in [('price_per_share', target['date']), ('price_at_filing', target.get('filing_date'))]:
            if field not in target['missing'] or not requested:
                continue
            check()
            requested_day = date.fromisoformat(requested)
            symbol = resolve_ticker(ticker, plan['former_tickers'], requested_day)
            key = (symbol, requested)
            if key not in prices:
                prices[key] = traded_close_on_or_before(symbol, requested_day, plan['splits'])
            info = prices[key]
            if not info or info.get('price') is None:
                result['missing'].append({'date': target['date'], 'field': field, 'reason': f'Нет котировки {symbol} на {requested}'})
                continue
            value = Decimal(str(info['price']))
            if target['currency'] != 'RUB':
                rate = Decimal(target['exchange_rate'] or '0')
                if rate <= 0:
                    result['missing'].append({'date': target['date'], 'field': field, 'reason': 'Нет курса валюты отчёта'})
                    continue
                value /= rate
            if not value.is_finite() or value <= 0:
                result['missing'].append({'date': target['date'], 'field': field, 'reason': 'Некорректная цена MOEX'})
                continue
            fields[field] = str(value.quantize(Decimal('0.000001')))
            provenance[field] = {'source': 'MOEX close', 'ticker': symbol, 'requested_date': requested,
                                 'actual_date': str(info.get('date') or requested), 'price_rub': str(info['price']),
                                 'retrieved_at': result['fetched_at']}
        if fields:
            result['reports'].append({**target, 'fields': fields, 'provenance': provenance})
        event(f'{ticker}: Мосбиржа {i + 1}/{len(targets)} дат; получено {len(fields)} полей')
    check()
    return result

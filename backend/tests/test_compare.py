"""Комментарий сравнения: фразы следуют из чисел, а не написаны заранее."""
from app.services.analysis.compare import comment


def card(name, **kw):
    base = dict(name=name, is_bank=False, pe=None, pb=None, roe=None, roe_spread=None, dividend_yield=None,
                streak=None, net_debt=None, debt_to_equity=None, current_ratio=None, growth_5=None,
                margin=None, sections={}, key_rate=None)
    base.update(kw)
    return base


def test_дешёвый_баланс_при_отдаче_ниже_ставки_названа_причина():
    cards = [card("А", pe=5.1, pb=0.88, roe=17.3, roe_spread=2.5), card("Б", pe=12.5, pb=0.40, roe=3.2, roe_spread=-15.9, key_rate=19.1)]
    text = " ".join(comment(cards))
    assert "Дешевле всех по прибыли **А**" in text
    assert "Дешевле всех по балансу **Б**" in text and "отдачей, а не скидкой" in text
    assert "(19,1%)" in text  # ставка названа


def test_числа_меняются_и_комментарий_за_ними():
    a, b = card("А", pe=5.0), card("Б", pe=12.0)
    assert "Дешевле всех по прибыли **А**" in comment([a, b])[0]
    a["pe"], b["pe"] = 14.0, 6.0          # пришёл новый отчёт
    assert "Дешевле всех по прибыли **Б**" in comment([a, b])[0]


def test_свод_и_оценка():
    cards = [card("А", sections={"price": True, "growth": True}, margin=-0.09),
             card("Б", sections={"price": True, "growth": False}, margin=0.2)]
    text = " ".join(comment(cards))
    assert "Все разделы свода защитного инвестора проходит **А**" in text
    assert "**Б** не проходит: рост" in text
    assert "Ниже опорной оценки торгуется только **Б**" in text


def test_одной_компании_сравнивать_не_с_чем():
    assert comment([card("А", pe=5)]) == []


def test_снимок_уже_в_рублях_и_второй_раз_не_переводится(monkeypatch):
    """Норникель отчитывается в долларах. Снимок «на сегодня» приходит уже в
    рублях, и раньше сравнение умножало его на курс ещё раз — выручка
    выходила 84 трлн ₽ вместо 1,08 трлн."""
    from types import SimpleNamespace

    from app.services.analysis import compare, multiplier_service, screen, screen_axes

    snapshot = {"ltm_revenue": 1_076_634.0, "ltm_net_income": 152_307.0, "ltm_fcf": 136_818.0,
                "equity": 885_213.0, "net_debt": 683_467.0, "shares_used": 15_286_339_700,
                "balance_report_id": 1393}
    monkeypatch.setattr(multiplier_service, "calculate_current_multipliers", lambda **_: snapshot)
    monkeypatch.setattr(screen_axes, "load", lambda db, c: [])
    monkeypatch.setattr(screen, "profile_for", lambda db, c: SimpleNamespace(key="default"))
    monkeypatch.setattr(screen, "apply", lambda *a, **k: SimpleNamespace(verdicts=[]))
    monkeypatch.setattr(compare, "_eps_by_year", lambda db, c: {})
    company = SimpleNamespace(id=80, ticker="GMKN", name="Норникель", brand_logo_url=None)

    row = compare.company_card(db=None, company=company, summary_fn=lambda _id: {})

    assert row["revenue"] == 1_076_634.0
    assert row["net_debt"] == 683_467.0
    assert round(row["book_per_share"], 1) == 57.9   # 885 млрд ₽ на 15,3 млрд акций

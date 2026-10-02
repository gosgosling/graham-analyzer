"""Комментарий сравнения: фразы следуют из чисел, а не написаны заранее."""
from app.services.analysis.compare import comment


def card(name, **kw):
    base = dict(name=name, is_bank=False, pe=None, pb=None, roe=None, roe_spread=None, dividend_yield=None,
                streak=None, net_debt=None, debt_to_equity=None, current_ratio=None, growth_5=None,
                margin=None, sections={})
    base.update(kw)
    return base


def test_дешёвый_баланс_при_отдаче_ниже_ставки_названа_причина():
    cards = [card("А", pe=5.1, pb=0.88, roe=17.3, roe_spread=2.5), card("Б", pe=12.5, pb=0.40, roe=3.2, roe_spread=-15.9)]
    text = " ".join(comment(cards))
    assert "Дешевле всех по прибыли **А**" in text
    assert "Дешевле всех по балансу **Б**" in text and "отдачей, а не скидкой" in text


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
    assert "Ниже опорной оценки торгуется **Б**" in text


def test_одной_компании_сравнивать_не_с_чем():
    assert comment([card("А", pe=5)]) == []

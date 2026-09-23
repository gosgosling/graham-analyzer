"""Ограждения перед оценкой: структура капитала и эффект Молодовского.

Опорные числа — из гл. 33 (с. 613–619) и гл. 34 (с. 634) пятого издания.
"""

import pytest

from app.services.analysis.valuation_guards import (
    COVERAGE_COMFORTABLE,
    COVERAGE_STRAINED,
    MOLODOVSKY_DEPRESSION,
    interest_coverage,
    molodovsky,
    structure,
)


# ── Покрытие процентов ─────────────────────────────────────────────────────

def test_coverage_is_profit_over_interest():
    assert interest_coverage(1600.0, 300.0) == pytest.approx(5.33, abs=0.01)


def test_coverage_treats_interest_as_positive_either_way():
    """Проценты хранятся положительным числом, но знак не должен решать."""
    assert interest_coverage(1000.0, 200.0) == interest_coverage(1000.0, -200.0)


def test_coverage_undefined_without_debt():
    """Бесконечного покрытия как числа не бывает — вывод делает structure."""
    assert interest_coverage(1000.0, 0.0) is None


def test_coverage_needs_both_terms():
    assert interest_coverage(None, 300.0) is None
    assert interest_coverage(1000.0, None) is None


# ── Приговор структуре капитала ────────────────────────────────────────────

def test_book_example_b_moderate_debt_passes():
    """У авторов компания B с 30% долга: покрытие 5,3× — приемлемо."""
    verdict = structure(1600.0, 300.0)
    assert verdict.verdict == "ok"
    assert verdict.valuation_allowed is True


def test_book_example_c_excessive_debt_is_strained_not_hidden():
    """Компания C с 80% долга: покрытие 2,0×.

    Прежде такую компанию прятали целиком. Теперь оценка считается, но
    дорожает: сказать «дорого и рискованно, вот насколько» полезнее, чем
    промолчать, — а на данных отказ выходил в восемь компаний из сорока пяти.
    """
    verdict = structure(1600.0, 800.0)
    assert verdict.coverage == pytest.approx(2.0)
    assert verdict.verdict == "strained"
    assert verdict.valuation_allowed is True
    assert "дорожает" in verdict.reason


def test_thresholds_match_the_book():
    assert COVERAGE_STRAINED == 2.5
    assert COVERAGE_COMFORTABLE == 5.0


def test_coverage_between_thresholds_is_fragile_but_allowed():
    verdict = structure(1600.0, 400.0)   # 4,0×
    assert verdict.verdict == "fragile"
    assert verdict.valuation_allowed is True
    assert "запас невелик" in verdict.reason


def test_debt_free_company_passes_without_a_coverage_number():
    verdict = structure(1000.0, 0.0)
    assert verdict.verdict == "ok"
    assert verdict.coverage is None
    assert "долга нет" in verdict.reason


def test_operating_loss_with_debt_is_refused():
    """Проценты платятся не из прибыли — размер долга уже неважен.

    Единственный оставшийся отказ: множитель здесь описывал бы не компанию, а
    деление на знак.
    """
    verdict = structure(-500.0, 200.0)
    assert verdict.coverage < 0
    assert verdict.verdict == "refuse"
    assert verdict.valuation_allowed is False
    assert "деление на знак" in verdict.reason


def test_missing_data_does_not_forbid_valuation():
    """Незаполненное поле — не то же, что плохие данные."""
    verdict = structure(None, None)
    assert verdict.verdict == "unknown"
    assert verdict.valuation_allowed is True


def test_verdict_is_serialisable():
    payload = structure(-500.0, 200.0).as_dict()
    assert payload["valuation_allowed"] is False
    assert payload["coverage"] == pytest.approx(-2.5)
    assert payload["reason"]
    assert "costs_credible" in payload


# ── Эффект Молодовского ────────────────────────────────────────────────────

def test_healthy_year_is_not_an_artifact():
    check = molodovsky(price=100.0, current_earnings_per_share=10.0,
                       normal_earnings_per_share=10.0)
    assert check.reported_multiple == pytest.approx(10.0)
    assert check.normal_multiple == pytest.approx(10.0)
    assert check.depression == pytest.approx(1.0)
    assert check.artifact is False


def test_collapsed_earnings_inflate_the_multiple():
    """Прибыль просела вдесятеро — P/E взлетел, но акция не подорожала."""
    check = molodovsky(price=100.0, current_earnings_per_share=1.0,
                       normal_earnings_per_share=10.0)
    assert check.reported_multiple == pytest.approx(100.0)
    assert check.normal_multiple == pytest.approx(10.0)
    assert check.depression == pytest.approx(0.1)
    assert check.artifact is True
    assert "артефакт деления" in check.reason


def test_moderate_dip_is_not_yet_an_artifact():
    """Половина от нормальной — заметный провал, но множитель лишь вдвое выше."""
    check = molodovsky(price=100.0, current_earnings_per_share=5.0,
                       normal_earnings_per_share=10.0)
    assert check.depression == pytest.approx(0.5)
    assert check.depression > MOLODOVSKY_DEPRESSION
    assert check.artifact is False


def test_loss_making_year_still_yields_a_normal_multiple():
    """Убыток — предельный случай того же: P/E нет, множитель к норме есть."""
    check = molodovsky(price=100.0, current_earnings_per_share=-3.0,
                       normal_earnings_per_share=10.0)
    assert check.reported_multiple is None
    assert check.normal_multiple == pytest.approx(10.0)
    assert check.artifact is True
    assert "год убыточный" in check.reason


def test_no_normal_earnings_means_no_verdict():
    """Без нормальной прибыли отличить провал от дороговизны нечем."""
    check = molodovsky(price=100.0, current_earnings_per_share=1.0,
                       normal_earnings_per_share=None)
    assert check.reported_multiple == pytest.approx(100.0)
    assert check.normal_multiple is None
    assert check.artifact is False


def test_loss_making_normal_earnings_gives_no_verdict():
    """Если и нормальная прибыль отрицательна, множителя не существует."""
    check = molodovsky(price=100.0, current_earnings_per_share=-1.0,
                       normal_earnings_per_share=-10.0)
    assert check.normal_multiple is None
    assert check.artifact is False


def test_growth_above_normal_is_not_an_artifact():
    """Прибыль выше нормальной занижает P/E — это другая ошибка, не эта."""
    check = molodovsky(price=100.0, current_earnings_per_share=20.0,
                       normal_earnings_per_share=10.0)
    assert check.reported_multiple == pytest.approx(5.0)
    assert check.normal_multiple == pytest.approx(10.0)
    assert check.artifact is False


def test_check_is_serialisable():
    payload = molodovsky(100.0, 1.0, 10.0).as_dict()
    assert payload["artifact"] is True
    assert payload["normal_multiple"] == pytest.approx(10.0)
    assert payload["reason"]


# ── Лизинговые проценты в знаменателе ──────────────────────────────────────


def test_лизинговые_проценты_входят_в_покрытие():
    """Случай Аэрофлота: аренда меняет вердикт на противоположный.

    Долг 611 млрд — почти целиком лизинг самолётов, а `finance_costs` его
    процентную часть не включает. Покрытие падает с 2,32 до 1,78 — почти на
    четверть.
    """
    from app.services.analysis.valuation_guards import interest_coverage

    without = interest_coverage(139_000.0, 60_000.0)
    with_lease = interest_coverage(139_000.0, 60_000.0, lease_interest=18_000.0)
    assert without == pytest.approx(2.32, abs=0.05)
    assert with_lease == pytest.approx(1.78, abs=0.05)

    # Величина, при которой аренда меняет и сам вердикт.
    assert structure(190_000.0, 60_000.0).verdict == "fragile"
    assert structure(190_000.0, 60_000.0,
                     lease_interest=18_000.0).verdict == "strained"


# ── Достоверность самих финансовых расходов ────────────────────────────────


def test_слишком_дешёвый_долг_делает_покрытие_недостоверным():
    """Фосагро: 7,3% при ключевой 19,1% — вдвое с лишним дешевле рынка."""
    verdict = structure(100_000.0, 24_000.0, debt=329_000.0, key_rate=19.1)
    assert verdict.verdict == "unknown"
    assert verdict.costs_credible is False
    assert "дешевле рынка" in verdict.reason


def test_слишком_дорогой_долг_тоже_недостоверен():
    """Татнефть: 103% на долг в 35 млрд — в поле лежит не стоимость долга."""
    verdict = structure(500_000.0, 36_000.0, debt=35_000.0, key_rate=19.1)
    assert verdict.verdict == "unknown"
    assert verdict.costs_credible is False


def test_правдоподобная_ставка_приговор_не_меняет():
    """МТС: 20,9% при ключевой 19,1% — цифре верим, покрытие 1,04 настоящее."""
    verdict = structure(155_000.0, 149_000.0, debt=713_000.0, key_rate=19.1)
    assert verdict.costs_credible is True
    assert verdict.verdict == "strained"
    assert verdict.implied_rate == pytest.approx(20.9, abs=0.1)


def test_без_долга_или_ставки_проверять_нечем():
    """Отсутствие проверки — не то же самое, что её провал."""
    assert structure(1600.0, 400.0, debt=None, key_rate=19.1).costs_credible is True
    assert structure(1600.0, 400.0, debt=5000.0, key_rate=None).costs_credible is True


def test_недостоверность_не_отменяет_отказ_при_убытке():
    """Смягчение работает только в пользу компании, а не против здравого смысла."""
    verdict = structure(-500.0, 200.0, debt=200.0, key_rate=19.1)
    assert verdict.verdict == "refuse"

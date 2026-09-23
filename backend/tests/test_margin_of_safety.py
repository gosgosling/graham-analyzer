"""Запас прочности, разделение капекса и правило роста по лестницам."""

import pytest

from app.services.analysis.company_valuation import (
    CASH_GROWTH_CAP,
    LADDER_CASH,
    LADDER_EARNINGS,
    LADDER_OWNER,
    ladder_growth,
)
from app.services.analysis.earning_power import YearPoint, maintenance_split
from app.services.analysis.margin_of_safety import (
    DANGEROUS,
    ACCEPTABLE,
    BOND_BETTER,
    EXPENSIVE,
    FAIR,
    FAVOURABLE,
    assess_safety,
    replacement_check,
)


# ── Разделение капекса ─────────────────────────────────────────────────────


def test_растущая_выручка_даёт_ростовой_капекс():
    """Прирост выручки оплачен мощностями — часть капекса идёт в рост."""
    rows = [(2020, 1000.0, 100.0), (2021, 1500.0, 200.0), (2022, 2000.0, 200.0)]
    out = maintenance_split(rows)
    maintenance, growth = out[2022]
    assert growth > 0
    assert maintenance + growth == pytest.approx(200.0)


def test_падающая_выручка_делает_весь_капекс_поддерживающим():
    """Главный случай: Лукойл-2025. Не строят — значит замещают.

    Без нижнего ограничения формула дала бы отрицательный ростовой капекс и
    поддерживающий выше фактического, то есть «поддерживали больше, чем
    потратили».
    """
    rows = [(2023, 8000.0, 720.0), (2024, 4400.0, 780.0), (2025, 3768.0, 775.0)]
    out = maintenance_split(rows)
    maintenance, growth = out[2025]
    assert growth == 0.0
    assert maintenance == pytest.approx(775.0)


def test_ростовой_не_превышает_капекс():
    """Скачок выручки вдвое не обнуляет поддержание."""
    rows = [(2020, 1000.0, 100.0), (2021, 1100.0, 110.0), (2022, 9000.0, 150.0)]
    maintenance, growth = maintenance_split(rows)[2022]
    assert growth <= 150.0
    assert maintenance >= 0.0


def test_первый_год_ряда_целиком_поддерживающий():
    """Прироста не с чем сравнить — считаем консервативно."""
    rows = [(2020, 1000.0, 100.0), (2021, 1200.0, 120.0)]
    assert maintenance_split(rows)[2020] == (100.0, 0.0)


def test_без_ряда_разделения_нет():
    """Одна точка — вызывающий обязан откатиться к вычету капекса целиком."""
    assert maintenance_split([(2020, 1000.0, 100.0)]) == {}
    assert maintenance_split([(2020, None, 100.0), (2021, 1000.0, None)]) == {}


# ── Правило роста по лестницам ─────────────────────────────────────────────


def test_щедрая_выплата_обнуляет_рост_прибыли():
    """При выплате 96% удерживать нечего — ноль прямо, а не 0,46%."""
    growth, source, note = ladder_growth(LADDER_EARNINGS, roe=15.0, payout=96.3)
    assert growth == 0.0
    assert source == "выплата"
    assert "удерживать нечего" in note


def test_умеренная_выплата_даёт_рост_из_удержания():
    growth, source, _ = ladder_growth(LADDER_EARNINGS, roe=20.0, payout=50.0)
    assert growth == pytest.approx(10.0)
    assert source == "удержание"


def test_денежная_лестница_не_берёт_рост_из_удержания():
    """Поток растёт от капекса, а капекс из потока уже вычтен."""
    growth, source, _ = ladder_growth(
        LADDER_CASH, roe=20.0, payout=50.0, observed=4.0
    )
    assert growth == pytest.approx(4.0)
    assert source == "наблюдаемый"


def test_наблюдаемый_рост_потока_подрезается_потолком():
    growth, source, note = ladder_growth(
        LADDER_CASH, roe=20.0, payout=50.0, observed=8.12
    )
    assert growth == CASH_GROWTH_CAP
    assert source == "наблюдаемый, подрезан"
    assert "8.1" in note


def test_сжимающийся_поток_не_даёт_отрицательного_роста():
    """Вечное сжатие формула Гордона описывает не лучше вечного взлёта."""
    growth, source, note = ladder_growth(
        LADDER_CASH, roe=20.0, payout=50.0, observed=-32.75
    )
    assert growth == 0.0
    assert source == "поток не растёт"
    assert note is not None


def test_прибыль_владельца_идёт_по_правилу_прибыли():
    owner, _, _ = ladder_growth(LADDER_OWNER, roe=20.0, payout=50.0)
    earnings, _, _ = ladder_growth(LADDER_EARNINGS, roe=20.0, payout=50.0)
    assert owner == earnings


# ── Запас прочности ────────────────────────────────────────────────────────


def test_запас_больше_трети_благоприятен():
    safety = assess_safety(
        price=60.0, reference=100.0, normal_earnings_per_share=15.0,
        risk_free_rate=10.0,
    )
    assert safety.signal == FAVOURABLE
    assert safety.value_margin == pytest.approx(0.4)


def test_тонкий_запас_по_ставке_понижает_благоприятный():
    """Полоса щедра из-за наших допущений о росте, отдача их не содержит."""
    safety = assess_safety(
        price=60.0, reference=100.0, normal_earnings_per_share=6.5,
        risk_free_rate=10.0,
    )
    assert safety.value_margin == pytest.approx(0.4)
    assert safety.signal == ACCEPTABLE
    assert any("запас по ставке" in note for note in safety.notes)


def test_цена_выше_оценки():
    safety = assess_safety(
        price=140.0, reference=100.0, normal_earnings_per_share=20.0,
        risk_free_rate=10.0,
    )
    assert safety.signal == EXPENSIVE
    assert safety.value_margin < 0


def test_около_стоимости():
    safety = assess_safety(
        price=95.0, reference=100.0, normal_earnings_per_share=20.0,
        risk_free_rate=10.0,
    )
    assert safety.signal == FAIR


def test_облигация_перекрывает_любой_запас():
    """Отдача ниже купона отменяет даже щедрую полосу — в этом суть гл. 20."""
    safety = assess_safety(
        price=50.0, reference=100.0, normal_earnings_per_share=4.0,
        risk_free_rate=16.0,
    )
    assert safety.signal == BOND_BETTER
    assert safety.value_margin == pytest.approx(0.5)


def test_непройденный_свод_понижает_но_не_гасит():
    """Гасить нельзя: свод валят тридцать четыре компании из тридцати шести."""
    safety = assess_safety(
        price=60.0, reference=100.0, normal_earnings_per_share=15.0,
        risk_free_rate=10.0, screen_clears=False,
    )
    assert safety.signal == ACCEPTABLE
    assert any("свод" in note for note in safety.notes)


def test_без_цены_сигнала_нет():
    assert assess_safety(price=None, reference=100.0,
                         normal_earnings_per_share=15.0,
                         risk_free_rate=10.0).signal == "no_signal"


# ── Восстановительная стоимость ────────────────────────────────────────────


def test_оценка_ниже_балансовой_это_диагноз():
    out = replacement_check(value_per_share=50.0, book_value_per_share=100.0)
    assert out["verdict"] == "ниже восстановительной"
    assert "не отрабатывают" in out["reason"]


def test_оценка_выше_балансовой_требует_объяснения():
    out = replacement_check(value_per_share=200.0, book_value_per_share=100.0)
    assert out["verdict"] == "выше восстановительной"


def test_вровень_без_замечаний():
    out = replacement_check(value_per_share=100.0, book_value_per_share=100.0)
    assert out["verdict"] == "вровень"
    assert out["reason"] is None


# ── Искажение начислениями ─────────────────────────────────────────────────


def test_разрыв_начислений_помечает_год():
    from app.services.analysis.earning_power import distortion_summary

    points = [
        YearPoint(year=2023, distorted=False),
        YearPoint(year=2024, distorted=True),
        YearPoint(year=2025, distorted=True),
    ]
    out = distortion_summary(points, window=3)
    assert out["years"] == [2024, 2025]
    assert out["share"] == pytest.approx(2 / 3, abs=1e-3)


def test_без_опорной_оценки_сигнала_нет():
    """Отдача без полосы приговором быть не может.

    Дефект, ради которого тест написан: ветка «нет полосы» падала в `fair`, и
    шесть компаний из сорока пяти получали подпись «около стоимости», не имея
    посчитанной стоимости. Среди них была та, которой оценка отказана за
    операционный убыток, — то есть подпись стояла ровно там, где сказано, что
    считать нечего.
    """
    from app.services.analysis.margin_of_safety import NO_SIGNAL

    safety = assess_safety(
        price=100.0, reference=None, normal_earnings_per_share=20.0,
        risk_free_rate=10.0,
    )
    assert safety.signal == NO_SIGNAL
    assert safety.value_margin is None
    assert "не посчитана" in safety.reason


# ── Признаки ловушки стоимости ─────────────────────────────────────────────


def test_глубокий_дисконт_к_балансу_это_признак_а_не_скидка():
    """Башнефть при P/B 0,20: рынок платит пятую часть капитала.

    Формула гл. 32 видит здесь дешевизну, потому что спрашивает только про
    размер потока к владельцу, а не про путь его туда.
    """
    from app.services.analysis.margin_of_safety import value_traps

    traps = value_traps(price_to_book=0.2, retention=None)
    assert [t["kind"] for t in traps] == ["deep_discount"]
    assert "меньше половины" in traps[0]["reason"]

    assert value_traps(price_to_book=1.4, retention=None) == []
    # Отрицательный или нулевой P/B — не дисконт, а отсутствие капитала.
    assert value_traps(price_to_book=0.0, retention=None) == []


def test_удержанное_не_осевшее_в_капитале_это_признак():
    """Тест Баффета: нерозданное обязано стать капиталом."""
    from app.services.analysis.margin_of_safety import value_traps

    leak = {"share": -0.26, "retained_per_share": 1364.0,
            "book_growth_per_share": -352.0}
    traps = value_traps(price_to_book=None, retention=leak)
    assert [t["kind"] for t in traps] == ["retention_leak"]

    healthy = {"share": 0.95, "retained_per_share": 100.0,
               "book_growth_per_share": 95.0}
    assert value_traps(price_to_book=None, retention=healthy) == []


def test_признак_ловушки_понижает_благоприятный_сигнал():
    """Понижает, а не гасит: дисконт бывает и настоящей скидкой."""
    without = assess_safety(
        price=60.0, reference=100.0, normal_earnings_per_share=15.0,
        risk_free_rate=10.0,
    )
    with_trap = assess_safety(
        price=60.0, reference=100.0, normal_earnings_per_share=15.0,
        risk_free_rate=10.0, price_to_book=0.4,
    )
    assert without.signal == FAVOURABLE
    assert with_trap.signal == ACCEPTABLE
    assert with_trap.traps and any("P/B" in n for n in with_trap.notes)


def test_крайний_дисконт_упирает_сигнал_в_потолок():
    """Случай Евротранса: понижения на ступень мало.

    Нормальная прибыль 34,6 ₽ на акцию, балансовая стоимость 214 ₽, цена
    21,9 ₽. Оценка по заработку даёт 165 ₽ и «запас 83%», тогда как цена упала
    со 147 ₽ на неплатежах по облигациям. Понижение на ступень оставляло
    «приемлемая», то есть предложение покупать.
    """
    safety = assess_safety(
        price=21.9, reference=150.0, normal_earnings_per_share=34.6,
        risk_free_rate=16.0, price_to_book=0.1,
    )
    assert safety.signal == FAIR
    assert any("P/B" in note for note in safety.notes)


def test_признаки_не_поднимают_дорогой_сигнал():
    """Ловушка только понижает — дорогую акцию она дешевле не делает."""
    safety = assess_safety(
        price=140.0, reference=100.0, normal_earnings_per_share=20.0,
        risk_free_rate=10.0, price_to_book=0.2,
    )
    assert safety.signal == EXPENSIVE


# ── Отказ при массовом искажении ───────────────────────────────────────────


def test_искажения_дорожают_но_не_отменяют_оценку():
    """Оценка даётся всегда, когда есть из чего считать.

    Отказ по искажениям здесь стоял ровно один день. Порог 0,6 от окна поверх
    определителя, помечавшего 66% всех лет, вынес в отказ двадцать компаний из
    тридцати — Норникель, Новатэк, Роснефть, МТС, Белугу. Бэктест показал рост
    точности с 54% до 67%, и рост был ложным: модель стала попадать чаще не
    потому, что считала лучше, а потому, что перестала считать трудное.

    Ненадёжность ряда — надбавка к ставке и оговорка в тексте, а не молчание.
    """
    from app.services.analysis.company_valuation import value_band
    from app.services.analysis.valuation_guards import structure

    def band(years):
        return value_band(
            payout=50.0, roe=12.0, risk_free_rate=16.0, risk_premium=5.0,
            normal_earnings={"прибыль": 100.0},
            structure=structure(1600.0, 200.0),
            distortion={"share": len(years) / 7, "count": len(years),
                        "of": 7, "years": years},
        )

    # Шесть лет из семи — случай Алросы. Оценка есть, и она дороже.
    worst = band([2019, 2020, 2022, 2023, 2024, 2025])
    assert worst.refused is False
    assert worst.low is not None
    assert worst.penalty.accruals > 0

    # Чем больше искажённых лет, тем ниже оценка — надбавка растёт вместе с ними.
    mild = band([2024])
    assert mild.low > worst.low


def test_тест_главы_15_не_делает_сигнал_благоприятным():
    """Башнефть: арифметически проходит гл. 15, но зелёного света не получает.

    Сперва тест поднимал сигнал до благоприятного, и это было ошибкой
    прочтения. Глава 15 — глава активного инвестора; защитному Грэм такие
    бумаги не предлагает вовсе, а активному разрешает лишь набором из многих,
    потому что часть обязательно окажется мёртвой. Свод по умолчанию защитный,
    и зелёный свет под ним означал бы не то, что написано в книге.

    При P/B 0,24 не поднимается и до приемлемой: дисконт глубже трёх четвертей
    сам по себе держит потолок.
    """
    safety = assess_safety(
        price=1221.0, reference=978.0, normal_earnings_per_share=589.0,
        risk_free_rate=16.0, price_to_book=0.23,
        ncav={"per_share": 1840.0, "threshold": 1227.0, "passes": True,
              "note": "цена ниже двух третей NCAV"},
    )
    assert safety.signal != FAVOURABLE
    assert safety.ncav["passes"] is True
    assert any("активного инвестора" in note for note in safety.notes)
    assert any("P/B" in note for note in safety.notes)


def test_тест_главы_15_поднимает_до_приемлемой_без_крайнего_дисконта():
    safety = assess_safety(
        price=80.0, reference=100.0, normal_earnings_per_share=25.0,
        risk_free_rate=16.0, price_to_book=0.9,
        ncav={"per_share": 150.0, "threshold": 100.0, "passes": True,
              "note": "цена ниже двух третей NCAV"},
    )
    assert safety.signal == ACCEPTABLE


def test_непройденный_тест_главы_15_сигнал_не_меняет():
    """Отрицательный NCAV — не приговор: у прибыльной компании его и не ждут."""
    safety = assess_safety(
        price=5381.0, reference=4047.0, normal_earnings_per_share=966.0,
        risk_free_rate=16.0,
        ncav={"per_share": -1038.0, "threshold": -692.0, "passes": False,
              "note": "NCAV отрицателен"},
    )
    assert safety.signal == EXPENSIVE
    assert safety.ncav["per_share"] == -1038.0


def test_рычаг_запрещает_называть_запас_запасом():
    """Аэрофлот: долг больше капитала в двенадцать раз.

    Запас по гл. 20 — это разница между заработком дела и безрисковой
    ставкой, но принадлежит она владельцу только после кредитора. При таком
    рычаге «запас 50%», посчитанный по прибыли, описывает положение держателя
    долга, а не акционера.
    """
    levered = assess_safety(
        price=32.7, reference=65.0, normal_earnings_per_share=18.5,
        risk_free_rate=16.0, leverage=12.05,
    )
    assert levered.signal == FAIR
    assert any("кредитору прежде акционера" in n for n in levered.notes)

    # Та же компания без долга запас сохраняет.
    clean = assess_safety(
        price=32.7, reference=65.0, normal_earnings_per_share=18.5,
        risk_free_rate=16.0, leverage=0.4,
    )
    assert clean.signal in (FAVOURABLE, ACCEPTABLE)


def test_опасность_старше_теста_главы_15():
    """Цена не бывает настолько хороша, чтобы это перестало иметь значение.

    Раньше гл. 15 перебивала рычаг по рассуждению «долг в NCAV уже вычтен».
    Рассуждение верное для арифметики и неверное для приговора: чистые
    оборотные активы считаются по балансу на отчётную дату, а проценты
    платятся каждый месяц, и до ликвидации, при которой NCAV бы реализовался,
    компанию может не довести именно обслуживание долга.
    """
    safety = assess_safety(
        price=1221.0, reference=978.0, normal_earnings_per_share=589.0,
        risk_free_rate=16.0, leverage=6.0,
        coverage_verdict="strained", structure_coverage=1.1,
        ncav={"per_share": 1840.0, "threshold": 1227.0, "passes": True,
              "note": "цена ниже двух третей NCAV"},
    )
    assert safety.signal == DANGEROUS


# ── Опасность ──────────────────────────────────────────────────────────────


def test_опасность_требует_доказанной_тяжести_а_не_одного_рычага():
    """X5: долг больше капитала вчетверо, но это аренда по МСФО 16.

    Покрытие процентов у неё не посчитано — `finance_costs` заполнен у
    пятнадцати компаний из сорока пяти. Пометить такую компанию опасной значит
    наказать её за нашу неполноту.
    """
    unknown = assess_safety(
        price=100.0, reference=200.0, normal_earnings_per_share=30.0,
        risk_free_rate=16.0, leverage=4.2,
    )
    assert unknown.signal != DANGEROUS
    assert any("не посчитано" in note for note in unknown.notes)
    # И запасом это всё же не называется.
    assert unknown.signal == FAIR

    proven = assess_safety(
        price=100.0, reference=200.0, normal_earnings_per_share=30.0,
        risk_free_rate=16.0, leverage=4.2,
        coverage_verdict="strained", structure_coverage=1.8,
    )
    assert proven.signal == DANGEROUS


def test_тонкое_покрытие_без_критического_не_опасность():
    """Белуга: 2,02× при рычаге 1,7 — запас невелик, но прибыль вдвое больше.

    Надбавку за это она получает в множителе; предупреждением такое называть
    нельзя, иначе метка обесценится.
    """
    safety = assess_safety(
        price=100.0, reference=120.0, normal_earnings_per_share=30.0,
        risk_free_rate=16.0, leverage=1.7,
        coverage_verdict="strained", structure_coverage=2.02,
    )
    assert safety.signal != DANGEROUS


def test_операционный_убыток_при_долге_это_опасность():
    safety = assess_safety(
        price=100.0, reference=200.0, normal_earnings_per_share=30.0,
        risk_free_rate=16.0, leverage=297.0,
        coverage_verdict="refuse", structure_coverage=-1.99,
    )
    assert safety.signal == DANGEROUS
    assert "операционном убытке" in safety.reason

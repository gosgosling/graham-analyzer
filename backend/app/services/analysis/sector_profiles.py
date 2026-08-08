"""
Отраслевые профили пороговых значений для скринера Грэма.

─────────────────────────────────────────────────────────────────────────────
Зачем это нужно

Грэм выводил свои пороги (P/E ≤ 15, P/B ≤ 1.5, D/E ≤ 0.5, Current Ratio ≥ 2)
для промышленных компаний США 1930-40-х годов. Применённые без разбора к
российскому рынку 2020-х, они дают ложные сигналы чаще, чем верные:

  • Current Ratio 0.67 у продуктового ритейлера — это бизнес-модель
    (покупатель платит сразу, поставщик получает через месяц), а не риск.
  • Total Liabilities / Equity 18× у той же компании — следствие МСФО 16:
    в обязательствах сидит капитализированная аренда тысяч магазинов.
  • P/B 0.3 у сетевой компании — не дешевизна, а переоценённая RAB-база
    с околонулевой регулируемой доходностью.
  • Дивдоходность 3% как «хорошо» при ключевой ставке ЦБ двузначного
    уровня — сигнал, потерявший смысл.

Профиль — это набор порогов и пометок «применимо / не применимо» для одной
группы отраслей. Он определяется по строке `Company.sector` (T-Invest / MOEX)
и по `report_type` отчёта ('bank' имеет приоритет над любым сектором).

Модуль — единственный источник истины по порогам: его использует
и backend-классификатор (`graham_analyser`), и фронтенд (получает профиль
в ответе `/multipliers/current` и раскрашивает карточки и таблицу).
─────────────────────────────────────────────────────────────────────────────
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Ключи метрик, для которых профиль задаёт пороги.
METRIC_KEYS: Tuple[str, ...] = ("pe", "pb", "de", "cr", "roe", "dy", "cir")


@dataclass(frozen=True)
class MetricBand:
    """
    Пороги одной метрики.

    Семантика зависит от `higher_is_better`:
        higher_is_better=False (P/E, P/B, D/E):
            value ≤ good  → "good";  value ≤ warn → "warn";  иначе "bad"
        higher_is_better=True  (ROE, Current Ratio, Div. Yield):
            value ≥ good  → "good";  value ≥ warn → "warn";  иначе "bad"

    applicable=False означает, что метрика для отрасли не имеет смысла:
    её показывают как справочную, но не окрашивают и не учитывают в вердикте.
    """
    good: Optional[float]
    warn: Optional[float]
    higher_is_better: bool
    hint: str
    applicable: bool = True
    note: Optional[str] = None
    tooltip_lines: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SectorProfile:
    key: str
    label: str
    summary: str
    bands: Dict[str, MetricBand]
    # Балансовый капитал отражает реальную стоимость бизнеса.
    # False → P/B и ROE интерпретировать с осторожностью (asset-light,
    # переоценённые основные средства, выкупы, большие выплаты).
    book_value_reliable: bool = True
    # Обязательства раздуты капитализированной арендой (МСФО 16) —
    # ориентироваться на чистый долг, а не на Total Liabilities / Equity.
    lease_heavy: bool = False


def _band(
    good: Optional[float],
    warn: Optional[float],
    higher_is_better: bool,
    hint: str,
    *,
    applicable: bool = True,
    note: Optional[str] = None,
    tooltip_lines: Tuple[str, ...] = (),
) -> MetricBand:
    return MetricBand(
        good=good,
        warn=warn,
        higher_is_better=higher_is_better,
        hint=hint,
        applicable=applicable,
        note=note,
        tooltip_lines=tooltip_lines,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Профили
# ─────────────────────────────────────────────────────────────────────────────

GRAHAM_DEFAULT = SectorProfile(
    key="industrial",
    label="Промышленность / прочее",
    summary="Классические пороги Грэма без отраслевых поправок.",
    bands={
        "pe": _band(15, 25, False, "≤ 15 — хорошо"),
        "pb": _band(1.5, 3.0, False, "≤ 1.5 — хорошо"),
        "de": _band(0.5, 1.0, False, "≤ 0.5 — хорошо"),
        "cr": _band(
            2.0, 1.5, True, "≥ 2.0 — норма по Грэму",
            tooltip_lines=(
                "Производство, промышленность: запасы и дебиторка критичны.",
                "Применяется классическая норма Грэма.",
                "≥ 2.0  —  хорошо (норма Грэма)",
                "1.5–2.0  —  приемлемо, следить за запасами",
                "< 1.5  —  внимание; < 1.0  —  красный флаг",
            ),
        ),
        "roe": _band(15, 10, True, "≥ 15% — хорошо"),
        "dy": _band(6, 3, True, "≥ 6% — хорошо"),
    },
)

BANK = SectorProfile(
    key="bank",
    label="Банки / финансы",
    summary=(
        "Депозиты клиентов — обязательства по природе, поэтому D/E и Current "
        "Ratio не применяются. Ликвидность оценивается нормативами ЦБ (Н1–Н3), "
        "эффективность — Cost-to-Income."
    ),
    bands={
        "pe": _band(10, 15, False, "≤ 10 — хорошо для банка"),
        "pb": _band(
            1.2, 2.0, False, "≤ 1.2 — хорошо для банка",
            note="Для банка балансовый капитал — ключевая метрика стоимости.",
        ),
        "de": _band(
            None, None, False, "D/E для банков не применим",
            applicable=False,
            note="Депозиты клиентов формируют обязательства: D/E 8–12× — норма.",
        ),
        "cr": _band(
            None, None, True, "CR для банков не применим",
            applicable=False,
            tooltip_lines=(
                "Для банков и финансовых организаций CR не используется:",
                "их «краткосрочные обязательства» — это депозиты клиентов,",
                "а не коммерческие долги. Ликвидность оценивается по",
                "нормативам ЦБ (Н1, Н2, Н3), а не по балансовому соотношению.",
            ),
        ),
        "roe": _band(15, 10, True, "≥ 15% — хорошо"),
        "dy": _band(8, 4, True, "≥ 8% — хорошо"),
        # Cost-to-Income: операционная эффективность банка. Порог жил
        # константами в graham_analyser — теперь здесь, вместе с остальными.
        "cir": _band(
            45, 55, False, "≤ 45% — эффективный банк",
            note="Операционные расходы к операционным доходам.",
        ),
    },
)

OIL_GAS_MINING = SectorProfile(
    key="oil_gas_mining",
    label="Нефтегаз / горнодобыча / металлургия",
    summary=(
        "Циклическая прибыль: низкий P/E на пике цикла обманчив, высокий на дне — "
        "нормален. Мощный операционный поток покрывает краткосрочный долг при CR < 1."
    ),
    bands={
        "pe": _band(
            8, 14, False, "≤ 8 — хорошо для циклички",
            note="На пике сырьевого цикла низкий P/E — ловушка: считайте от средней прибыли.",
        ),
        "pb": _band(1.2, 2.5, False, "≤ 1.2 — хорошо"),
        "de": _band(1.0, 2.0, False, "≤ 1.0 — хорошо"),
        "cr": _band(
            1.0, 0.7, True, "≥ 1.0 — норма для нефтегаза",
            tooltip_lines=(
                "Нефтегаз, металлургия: мощный операционный поток",
                "покрывает краткосрочный долг даже при CR < 1.",
                "≥ 1.0  —  хорошо",
                "0.7–1.0  —  допустимо, смотри D/E и cash flow",
                "< 0.7  —  агрессивная долговая политика, копай глубже",
            ),
        ),
        "roe": _band(15, 10, True, "≥ 15% — хорошо"),
        "dy": _band(8, 4, True, "≥ 8% — хорошо"),
        # Cost-to-Income: операционная эффективность банка. Порог жил
        # константами в graham_analyser — теперь здесь, вместе с остальными.
        "cir": _band(
            45, 55, False, "≤ 45% — эффективный банк",
            note="Операционные расходы к операционным доходам.",
        ),
    },
)

UTILITIES = SectorProfile(
    key="utilities",
    label="Коммунальные / электроэнергетика",
    summary=(
        "Регулируемый тариф ограничивает и рентабельность, и рост. Огромные "
        "основные средства делают P/B малоинформативным, а высокий capex "
        "съедает свободный поток при формально прибыльном отчёте."
    ),
    book_value_reliable=False,
    bands={
        "pe": _band(8, 14, False, "≤ 8 — хорошо"),
        "pb": _band(
            0.5, 1.0, False, "≤ 0.5 — хорошо",
            note=(
                "Сети и генерация почти всегда торгуются ниже баланса: "
                "низкий P/B здесь — норма, а не сигнал дешевизны."
            ),
        ),
        "de": _band(0.8, 1.5, False, "≤ 0.8 — хорошо"),
        "cr": _band(
            1.0, 0.7, True, "≥ 1.0 — норма для коммунальных",
            tooltip_lines=(
                "Коммунальные, электроэнергетика: регулируемый тариф",
                "обеспечивает предсказуемый поток. CR < 1 — ок.",
                "≥ 1.0  —  хорошо",
                "0.7–1.0  —  норма, смотри долг и инвестиции",
                "< 0.7  —  требует пояснения (разовые капвложения?)",
            ),
        ),
        "roe": _band(
            10, 5, True, "≥ 10% — хорошо для регулируемой отрасли",
            note="Разрешённая доходность регулятора ограничивает ROE сверху.",
        ),
        "dy": _band(8, 4, True, "≥ 8% — хорошо"),
    },
)

RETAIL_GROCERY = SectorProfile(
    key="retail_grocery",
    label="Продуктовый ритейл / FMCG",
    summary=(
        "Отрицательный оборотный капитал — не риск, а модель: покупатель платит "
        "сразу, поставщик получает через месяц. Аренда магазинов по МСФО 16 "
        "раздувает обязательства, выкупы и выплаты сжимают капитал."
    ),
    book_value_reliable=False,
    lease_heavy=True,
    bands={
        "pe": _band(12, 20, False, "≤ 12 — хорошо"),
        "pb": _band(
            3.0, 6.0, False, "≤ 3.0 — хорошо",
            note=(
                "Ритейл asset-light: балансовый капитал мал и легко искажается "
                "выкупами и дивидендами, поэтому P/B слабо связан со стоимостью."
            ),
        ),
        "de": _band(
            3.0, 6.0, False, "≤ 3.0 — хорошо",
            note=(
                "Total Liabilities включает арендные обязательства по МСФО 16 — "
                "это не долг в грэмовском смысле. Ориентируйтесь на ND/FCF."
            ),
        ),
        "cr": _band(
            1.0, 0.6, True, "≥ 1.0 — норма для продуктового ритейла",
            tooltip_lines=(
                "Продуктовый ритейл живёт на отрицательном оборотном капитале:",
                "выручка приходит наличными сразу, а поставщикам платят через",
                "30–45 дней. CR ниже 1 здесь — признак сильной переговорной",
                "позиции, а не приближающегося дефолта.",
                "≥ 1.0  —  комфортно",
                "0.6–1.0  —  норма для сети с высокой оборачиваемостью",
                "< 0.6  —  проверить оборачиваемость запасов и график погашений",
            ),
        ),
        "roe": _band(
            20, 12, True, "≥ 20% — хорошо",
            note="При малом капитале ROE легко превышает 50% — смотрите разложение.",
        ),
        "dy": _band(8, 4, True, "≥ 8% — хорошо"),
    },
)

RETAIL_GENERAL = SectorProfile(
    key="retail_general",
    label="Непродуктовый ритейл / дистрибуция",
    summary=(
        "Медленная оборачиваемость и товарные запасы: в отличие от продуктовых "
        "сетей, здесь дефицит ликвидности — реальный риск."
    ),
    lease_heavy=True,
    bands={
        "pe": _band(12, 20, False, "≤ 12 — хорошо"),
        "pb": _band(2.0, 4.0, False, "≤ 2.0 — хорошо"),
        "de": _band(
            2.0, 4.0, False, "≤ 2.0 — хорошо",
            note="Обязательства включают аренду торговых площадей (МСФО 16).",
        ),
        "cr": _band(
            1.5, 1.0, True, "≥ 1.5 — хорошо",
            tooltip_lines=(
                "Непродуктовый ритейл и дистрибуция: оборачиваемость запасов",
                "ниже, чем у продуктовых сетей, отсрочка от поставщиков короче.",
                "≥ 1.5  —  хорошо",
                "1.0–1.5  —  приемлемо, следить за запасами",
                "< 1.0  —  красный флаг",
            ),
        ),
        "roe": _band(15, 10, True, "≥ 15% — хорошо"),
        "dy": _band(6, 3, True, "≥ 6% — хорошо"),
    },
)

IT_TELECOM = SectorProfile(
    key="it_telecom",
    label="IT / телеком / цифровые сервисы",
    summary=(
        "Asset-light: главные активы не стоят на балансе, поэтому P/B и ROE "
        "почти не несут информации. Оценка идёт от денежного потока и роста."
    ),
    book_value_reliable=False,
    bands={
        "pe": _band(20, 30, False, "≤ 20 — хорошо для растущего IT"),
        "pb": _band(
            4.0, 8.0, False, "≤ 4.0 — хорошо",
            note="Интеллектуальный капитал и бренд не отражены в балансе.",
        ),
        "de": _band(1.0, 2.0, False, "≤ 1.0 — хорошо"),
        "cr": _band(
            1.5, 1.0, True, "≥ 1.5 — хорошо для IT / цифровых сервисов",
            tooltip_lines=(
                "IT, телеком, платформы: обычно asset-light, мало запасов,",
                "высокая маржа или подписная выручка. Классический CR ≥ 2 для",
                "«магазина с полки» здесь часто завышен; ориентиры мягче.",
                "≥ 1.5  —  хорошо",
                "1.0–1.5  —  приемлемо",
                "< 1.0  —  нетипично, смотри структуру обязательств и cash flow",
            ),
        ),
        "roe": _band(20, 12, True, "≥ 20% — хорошо"),
        "dy": _band(
            5, 2, True, "≥ 5% — хорошо",
            note="Растущие компании реинвестируют прибыль — низкая доходность нормальна.",
        ),
    },
)

DEVELOPER = SectorProfile(
    key="developer",
    label="Строительство / девелопмент",
    summary=(
        "Проектный долг под эскроу нельзя складывать с корпоративным: он "
        "обеспечен деньгами покупателей на счетах. Авансы дольщиков сидят в "
        "краткосрочных обязательствах и занижают CR."
    ),
    bands={
        "pe": _band(8, 15, False, "≤ 8 — хорошо"),
        "pb": _band(1.0, 2.0, False, "≤ 1.0 — хорошо"),
        "de": _band(
            3.0, 6.0, False, "≤ 3.0 — хорошо",
            note=(
                "Проектное финансирование под эскроу формально увеличивает долг, "
                "но обеспечено средствами дольщиков — оценивайте чистый долг "
                "за вычетом остатков на эскроу."
            ),
        ),
        "cr": _band(
            1.2, 0.8, True, "≥ 1.2 — норма для строителей",
            tooltip_lines=(
                "Строительство: авансы покупателей квартир — краткосрочные",
                "обязательства, что занижает CR. Важнее смотреть динамику",
                "и эскроу-счета (в РФ — обязательно с 2019 г.).",
                "≥ 1.2  —  хорошо",
                "0.8–1.2  —  обычная ситуация для девелопера",
                "< 0.8  —  изучить структуру обязательств",
            ),
        ),
        "roe": _band(15, 10, True, "≥ 15% — хорошо"),
        "dy": _band(6, 3, True, "≥ 6% — хорошо"),
    },
)

TRANSPORT = SectorProfile(
    key="transport",
    label="Транспорт / логистика",
    summary=(
        "Капиталоёмкий флот и подвижной состав финансируются лизингом, который "
        "по МСФО 16 попадает в обязательства."
    ),
    lease_heavy=True,
    bands={
        "pe": _band(10, 18, False, "≤ 10 — хорошо"),
        "pb": _band(1.5, 3.0, False, "≤ 1.5 — хорошо"),
        "de": _band(
            1.5, 3.0, False, "≤ 1.5 — хорошо",
            note="Лизинг судов, вагонов и самолётов увеличивает обязательства.",
        ),
        "cr": _band(
            1.2, 0.8, True, "≥ 1.2 — хорошо",
            tooltip_lines=(
                "Транспорт и логистика: капиталоёмкий парк, значительная часть",
                "обязательств — лизинговые платежи ближайшего года.",
                "≥ 1.2  —  хорошо",
                "0.8–1.2  —  приемлемо",
                "< 0.8  —  проверить график лизинговых платежей",
            ),
        ),
        "roe": _band(15, 10, True, "≥ 15% — хорошо"),
        "dy": _band(6, 3, True, "≥ 6% — хорошо"),
    },
)

ALL_PROFILES: Tuple[SectorProfile, ...] = (
    BANK,
    OIL_GAS_MINING,
    UTILITIES,
    RETAIL_GROCERY,
    RETAIL_GENERAL,
    IT_TELECOM,
    DEVELOPER,
    TRANSPORT,
    GRAHAM_DEFAULT,
)

_BY_KEY: Dict[str, SectorProfile] = {p.key: p for p in ALL_PROFILES}


# ─────────────────────────────────────────────────────────────────────────────
# Определение профиля по сектору
# ─────────────────────────────────────────────────────────────────────────────

_BANK_WORDS = (
    "bank", "банк", "financial", "финанс", "insurance", "страхов",
    "leasing", "лизинг", "finance",
)
# GICS-сектор "energy" — это нефтегаз, а не электроэнергетика:
# электрогенерация и сети живут в "utilities".
_OIL_GAS_WORDS = (
    "oil", "gas", "нефт", "газ", "mining", "металл", "coal", "уголь",
    "petro", "горнодобыв", "золото", "silver", "copper", "alumin",
    "steel", "basic_materials", "basic materials", "materials", "energy",
)
_UTILITY_WORDS = (
    # T-Invest отдаёт сетевые и генерирующие компании как "electrocity"
    # (именно с такой опечаткой), поэтому пишем оба варианта написания.
    "util", "electric", "electrocity", "electricity",
    "энергетик", "электро", "тепло", "water", "вода",
    "коммунал", "generation", "генерац", "энерго", "сетев",
)
_IT_WORDS = (
    "software", "hardware", "internet", "computer", "semiconductor", "cyber",
    "cloud", "saas", "digital", "platform", "technology", "technologies",
    "informatics", "telecom", "телеком", "связь", "cellular", "mobile",
    "мобильн", "медиа", "media", "gaming", "програм", "информац", "цифров",
    "облак",
)
_IT_GICS_WORDS = (
    "communication_services", "communication services",
    "information_technology", "information technology",
    "it_services", "it services",
    "internet_software", "internet software",
)
_GROCERY_WORDS = (
    "grocery", "supermarket", "hypermarket", "food", "продукт", "продовольств",
    "fmcg", "consumer_staples", "consumer staples", "consumer_defensive",
    "consumer defensive", "фарм", "pharma", "drugstore",
)
_RETAIL_WORDS = (
    "retail", "ритейл", "торговл", "маркет", "distribution", "дистрибуц",
    "shopping", "потребител", "consumer_discretionary", "consumer discretionary",
    "consumer_cyclical", "consumer cyclical",
    # T-Invest не делит потребительский сектор на staples и discretionary
    # и отдаёт голое "consumer" и для Магнита, и для М.Видео. Без этого
    # ключа весь ритейл уходил в классический грэмовский профиль.
    "consumer",
)
# "green_energy" у T-Invest — генерация, но подстрока "energy" утащила бы её
# в нефтегаз, поэтому проверяется отдельно и раньше.
_GREEN_UTILITY_WORDS = (
    "green_energy", "green energy", "green_buildings", "green buildings",
    "renewable", "возобновляем", "зелёная энерг", "зеленая энерг",
)
_DEVELOPER_WORDS = (
    "construct", "строит", "develo", "девелоп", "real estate", "real_estate",
    "недвижим", "realty",
)
_TRANSPORT_WORDS = (
    "transport", "транспорт", "logistic", "логист", "shipping", "перевоз",
    "airline", "авиа", "railway", "железнодорож", "port", "порт",
)


def _contains_any(text: str, words: Tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def resolve_sector_profile(
    sector: Optional[str],
    report_type: Optional[str] = None,
) -> SectorProfile:
    """
    Подбирает профиль по сектору компании и типу отчёта.

    `report_type='bank'` имеет приоритет: тип отчёта задаётся аналитиком явно
    и надёжнее строки сектора из внешнего API.

    Порядок проверки важен: продуктовый ритейл ищется до общего (иначе
    «consumer_staples» уйдёт в непродуктовый), а IT — до энергетики
    (иначе «энерго» поймает «Энергосбыт-IT»-подобные названия).
    """
    if (report_type or "").strip().lower() == "bank":
        return BANK

    s = (sector or "").strip().lower()
    if not s:
        return GRAHAM_DEFAULT

    # Сектор «financial» объединяет банки, страховщиков, биржи и холдинги,
    # поэтому банковский профиль по нему НЕ назначается: он следует только из
    # типа компании (report_type='bank'). Раньше отсюда АФК Система получала
    # банковские пороги и норматив достаточности капитала.
    if s == "it" or _contains_any(s, _IT_GICS_WORDS) or _contains_any(s, _IT_WORDS):
        return IT_TELECOM
    if _contains_any(s, _GROCERY_WORDS):
        return RETAIL_GROCERY
    if _contains_any(s, _RETAIL_WORDS):
        return RETAIL_GENERAL
    if _contains_any(s, _DEVELOPER_WORDS):
        return DEVELOPER
    if _contains_any(s, _TRANSPORT_WORDS):
        return TRANSPORT
    if _contains_any(s, _GREEN_UTILITY_WORDS):
        return UTILITIES
    if _contains_any(s, _OIL_GAS_WORDS):
        return OIL_GAS_MINING
    if _contains_any(s, _UTILITY_WORDS):
        return UTILITIES
    return GRAHAM_DEFAULT


def get_profile_by_key(key: Optional[str]) -> SectorProfile:
    """Профиль по его ключу; неизвестный ключ → классический Грэм."""
    return _BY_KEY.get((key or "").strip().lower(), GRAHAM_DEFAULT)


def resolve_profile(
    sector: Optional[str],
    report_type: Optional[str] = None,
    override_key: Optional[str] = None,
) -> SectorProfile:
    """
    Профиль компании с учётом ручного закрепления аналитиком.

    `override_key` (Company.sector_profile_key) сильнее автоопределения:
    сектор T-Invest слишком крупный, и только аналитик знает, что «consumer»
    у конкретной компании — это продуктовая сеть, а не магазин электроники.
    Неизвестный ключ игнорируется, чтобы опечатка не сбрасывала пороги
    молча в классического Грэма.
    """
    key = (override_key or "").strip().lower()
    if key and key in _BY_KEY:
        return _BY_KEY[key]
    return resolve_sector_profile(sector, report_type)


def available_profiles() -> Tuple[Dict[str, str], ...]:
    """Список профилей для выпадающего списка в карточке компании."""
    return tuple(
        {"key": p.key, "label": p.label, "summary": p.summary}
        for p in ALL_PROFILES
    )


# ─────────────────────────────────────────────────────────────────────────────
# Оценка значения по профилю
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_metric(
    profile: SectorProfile,
    metric: str,
    value: Optional[float],
) -> str:
    """
    Статус значения метрики в рамках профиля.

    Returns: "good" | "normal" | "bad" | "n/a"
        "n/a" — метрика неприменима к отрасли либо значения нет.
    """
    band = profile.bands.get(metric)
    if band is None or not band.applicable:
        return "n/a"
    if value is None or band.good is None or band.warn is None:
        return "n/a"
    if band.higher_is_better:
        if value >= band.good:
            return "good"
        return "normal" if value >= band.warn else "bad"
    if value <= band.good:
        return "good"
    return "normal" if value <= band.warn else "bad"


def profile_to_dict(profile: SectorProfile) -> Dict:
    """Сериализация профиля для API (плоская, без dataclass-специфики)."""
    return {
        "key": profile.key,
        "label": profile.label,
        "summary": profile.summary,
        "book_value_reliable": profile.book_value_reliable,
        "lease_heavy": profile.lease_heavy,
        "bands": {
            name: {
                "good": band.good,
                "warn": band.warn,
                "higher_is_better": band.higher_is_better,
                "hint": band.hint,
                "applicable": band.applicable,
                "note": band.note,
                "tooltip_lines": list(band.tooltip_lines),
            }
            for name, band in profile.bands.items()
        },
    }

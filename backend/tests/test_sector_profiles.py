"""Отраслевые профили: подбор по сектору, ручное закрепление, оценка метрик.

Эти тесты защищают от тихих регрессий в маппинге секторов: строка сектора
приходит из внешнего API (T-Invest), и один неудачно добавленный синоним
переводит целую отрасль на чужие пороги, ничего не ломая в интерфейсе.
"""
import pytest

from app.services.analysis.sector_profiles import (
    BANK,
    GRAHAM_DEFAULT,
    available_profiles,
    evaluate_metric,
    get_profile_by_key,
    profile_to_dict,
    resolve_profile,
    resolve_sector_profile,
)


# ─── Подбор профиля по сектору ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "sector, expected_key",
    [
        # Сектор «банки» больше НЕ даёт банковский профиль: в него же попадают
        # страховщики, биржи и холдинги. Профиль следует из типа компании.
        ("banks", "industrial"),
        ("Финансы и банки", "industrial"),
        ("it", "it_telecom"),
        ("telecom", "it_telecom"),
        ("consumer", "retail_general"),
        ("Продуктовый ритейл", "retail_grocery"),
        ("green_energy", "utilities"),
        ("electrocity", "utilities"),
        ("oil_and_gas", "oil_gas_mining"),
        ("materials", "oil_gas_mining"),
        ("Девелопмент и строительство", "developer"),
        ("Транспорт", "transport"),
        ("machinery", "industrial"),
        ("", "industrial"),
        (None, "industrial"),
    ],
)
def test_sector_maps_to_expected_profile(sector, expected_key):
    assert resolve_sector_profile(sector).key == expected_key


def test_bank_report_type_beats_sector_string():
    """Тип отчёта ставит аналитик руками — он надёжнее строки из API."""
    assert resolve_sector_profile("Промышленность", report_type="bank") is BANK


# ─── Ручное закрепление профиля аналитиком ──────────────────────────────────


def test_manual_override_beats_auto_detection():
    profile = resolve_profile("consumer", override_key="retail_grocery")
    assert profile.key == "retail_grocery"


def test_unknown_override_key_falls_back_to_auto_detection():
    """Опечатка в ключе не должна молча сбрасывать пороги в классического Грэма."""
    profile = resolve_profile("consumer", override_key="retail_grosery")
    assert profile.key == "retail_general"


def test_empty_override_uses_sector():
    assert resolve_profile("it", override_key=None).key == "it_telecom"
    assert resolve_profile("it", override_key="   ").key == "it_telecom"


def test_unknown_profile_key_gives_graham_default():
    assert get_profile_by_key("нет-такого") is GRAHAM_DEFAULT


def test_all_offered_profiles_are_resolvable():
    """Каждый ключ из выпадающего списка обязан находиться по ключу."""
    for option in available_profiles():
        assert get_profile_by_key(option["key"]).key == option["key"]


# ─── Оценка значения по порогам ─────────────────────────────────────────────


def test_lower_is_better_metric():
    """P/E у промышленной компании: ≤ 15 хорошо, ≤ 25 терпимо, выше плохо."""
    assert evaluate_metric(GRAHAM_DEFAULT, "pe", 12) == "good"
    assert evaluate_metric(GRAHAM_DEFAULT, "pe", 15) == "good"
    assert evaluate_metric(GRAHAM_DEFAULT, "pe", 20) == "normal"
    assert evaluate_metric(GRAHAM_DEFAULT, "pe", 30) == "bad"


def test_higher_is_better_metric():
    """ROE: ≥ 15% хорошо, ≥ 10% терпимо, ниже плохо."""
    assert evaluate_metric(GRAHAM_DEFAULT, "roe", 20) == "good"
    assert evaluate_metric(GRAHAM_DEFAULT, "roe", 12) == "normal"
    assert evaluate_metric(GRAHAM_DEFAULT, "roe", 5) == "bad"


def test_bank_thresholds_are_stricter_than_industrial():
    """P/E 12 — норма для промышленности и уже дороговато для банка."""
    assert evaluate_metric(GRAHAM_DEFAULT, "pe", 12) == "good"
    assert evaluate_metric(BANK, "pe", 12) == "normal"


def test_metric_not_applicable_to_sector():
    """У банка D/E и Current Ratio не окрашиваются и не идут в вердикт."""
    assert evaluate_metric(BANK, "de", 8.0) == "n/a"
    assert evaluate_metric(BANK, "cr", 0.4) == "n/a"


def test_missing_value_and_unknown_metric():
    assert evaluate_metric(GRAHAM_DEFAULT, "pe", None) == "n/a"
    assert evaluate_metric(GRAHAM_DEFAULT, "нет-такой-метрики", 1.0) == "n/a"


# ─── Сериализация для фронта ────────────────────────────────────────────────


def test_profile_serialization_keeps_contract():
    data = profile_to_dict(BANK)

    assert data["key"] == "bank"
    assert set(data) >= {"key", "label", "summary", "bands", "book_value_reliable", "lease_heavy"}
    # Фронт красит метрики по этим полям — они должны быть у каждой полосы.
    for band in data["bands"].values():
        assert set(band) >= {"good", "warn", "higher_is_better", "applicable"}
    assert data["bands"]["de"]["applicable"] is False

# ─── Сектор «financial» ≠ банк ──────────────────────────────────────────────


def test_financial_sector_alone_does_not_make_a_bank():
    """АФК Система и SFI имеют сектор financial, но банковского бизнеса не ведут.

    Раньше строка сектора назначала банковский профиль, и холдинг получал
    пороги P/B, ROE и норматив достаточности капитала, которого у него нет.
    """
    for sector in ("financial", "banks", "Финансы и банки", "insurance"):
        assert resolve_sector_profile(sector).key != "bank"


def test_bank_profile_comes_from_report_type_only():
    assert resolve_sector_profile("financial", report_type="bank") is BANK
    assert resolve_sector_profile("financial", report_type="general").key != "bank"

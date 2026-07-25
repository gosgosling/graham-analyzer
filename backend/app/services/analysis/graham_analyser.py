"""
Классификация компаний по принципам Грэма с отраслевой поправкой.

Пороги берутся не из константы «как у Грэма», а из отраслевого профиля
(`sector_profiles`): для банка не считается D/E, для продуктового ритейлера
Current Ratio 0.7 — норма, для сетевой компании P/B 0.4 не означает дешевизну.
Профиль определяется по сектору компании и типу отчёта.

Правило вердикта:
    undervalued — все применимые метрики в зелёной зоне профиля
    stable      — ни одна применимая метрика не в красной зоне
    overvalued  — хотя бы одна применимая метрика в красной зоне

Неприменимые метрики (статус "n/a") в вердикте не участвуют: отсутствие
Current Ratio у банка не должно понижать его оценку.
"""
from typing import Dict, Optional

from app.services.analysis.sector_profiles import (
    SectorProfile,
    evaluate_metric,
    resolve_profile,
)

# Cost-to-Income — банковская метрика операционной эффективности,
# в отраслевые профили не входит: она применима только к банкам.
_CIR_GOOD = 45.0
_CIR_NORMAL = 55.0


def classify_company(
    multipliers: dict,
    report_type: str = "general",
    sector: Optional[str] = None,
    profile_key: Optional[str] = None,
) -> dict:
    """
    Классифицирует компанию по мультипликаторам с учётом отрасли.

    Args:
        multipliers: словарь с мультипликаторами (pe_ratio, pb_ratio, roe,
                     debt_to_equity, current_ratio, dividend_yield,
                     cost_to_income)
        report_type: "general" | "bank" — тип отчёта, задан аналитиком
        sector: строка сектора компании (T-Invest / MOEX); уточняет профиль
        profile_key: профиль, закреплённый аналитиком вручную; сильнее сектора

    Returns:
        dict со статусами по метрикам ("good" | "normal" | "bad" | "n/a"),
        итоговым вердиктом и описанием применённого профиля.
    """
    profile = resolve_profile(sector, report_type, profile_key)

    statuses = {
        "pe": evaluate_metric(profile, "pe", multipliers.get("pe_ratio")),
        "pb": evaluate_metric(profile, "pb", multipliers.get("pb_ratio")),
        "de": evaluate_metric(profile, "de", multipliers.get("debt_to_equity")),
        "cr": evaluate_metric(profile, "cr", multipliers.get("current_ratio")),
        "roe": evaluate_metric(profile, "roe", multipliers.get("roe")),
        "dy": evaluate_metric(profile, "dy", multipliers.get("dividend_yield")),
    }

    cir_status = _evaluate_cir(profile, multipliers.get("cost_to_income"))

    return {
        "classify": _verdict(statuses, cir_status),
        "pe_ratio_status": statuses["pe"],
        "pb_ratio_status": statuses["pb"],
        "debt_status": statuses["de"],
        "liquidity_status": statuses["cr"],
        "profitability_status": statuses["roe"],
        "dividend_status": statuses["dy"],
        "cir_status": cir_status,
        "profile_key": profile.key,
        "profile_label": profile.label,
    }


def _evaluate_cir(profile: SectorProfile, cost_to_income: Optional[float]) -> str:
    if profile.key != "bank" or cost_to_income is None:
        return "n/a"
    if cost_to_income <= _CIR_GOOD:
        return "good"
    return "normal" if cost_to_income <= _CIR_NORMAL else "bad"


def _verdict(statuses: Dict[str, str], cir_status: str) -> str:
    applicable = [s for s in (*statuses.values(), cir_status) if s != "n/a"]
    if not applicable:
        return "overvalued"
    if all(s == "good" for s in applicable):
        return "undervalued"
    if any(s == "bad" for s in applicable):
        return "overvalued"
    return "stable"

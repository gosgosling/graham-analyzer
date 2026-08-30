"""Аудит достоверности данных: чему можно верить, а что показывать нельзя.

Проверки нарочно **структурные**: они не сверяются ни с каким внешним
источником, а опираются на то, что величины внутри отчёта связаны между собой
(активы = обязательства + капитал; резерв не больше портфеля) и что ряд
одной величины по годам не может скакнуть ровно в десять раз.

Три уровня, и смешивать их нельзя:

    defect   — заведомая ошибка ввода: потерянный разряд, скопированное поле,
               баланс, расходящийся сильнее, чем на любую неконтролирующую долю
    gap      — расхождение, объяснимое отсутствующим в модели полем
               (неконтролирующая доля), то есть пробел схемы, а не данных
    suspect  — повод посмотреть глазами, но может быть и правдой

Пригодной к показу считается компания без defect'ов.

Здесь только проверки и их результат. Печать и разбор аргументов — в
`scripts.audit_data`, которая этот модуль и вызывает.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_report import FinancialReport

DEFECT, GAP, SUSPECT = "defect", "gap", "suspect"

# Разрыв баланса до этой доли активов объясняется неконтролирующей долей:
# у Роснефти и Газпром нефти она как раз 4-5%, и отдельного поля под неё в
# модели нет. Всё, что выше, неконтролирующей долей уже не объяснить.
NCI_TOLERANCE = 0.10
# Округление отчёта.
BALANCE_TOLERANCE = 0.01
# Разряды, которые теряют и добавляют при ручном вводе.
DECADES = (10, 100, 1000)
# Насколько скачок должен быть близок к степени десяти, чтобы считаться
# разрядом, а не событием в компании.
DECADE_FIT = 0.15

# Капитал не обрушивается, пока компания прибыльна: падение больше трети при
# положительной прибыли — это либо ошибка ввода, либо списание активов
# масштаба целого бизнеса. Второе бывает по-настоящему (ЛУКОЙЛ в 2025-м после
# санкций SDN потерял половину активов), поэтому уровень — «смотреть».
EQUITY_COLLAPSE = 0.30

SCALE_WATCH = (
    "revenue", "net_income", "total_assets", "total_liabilities", "equity",
    "operating_cash_flow", "capex", "cash_and_equivalents", "debt",
    "gross_loans", "customer_deposits",
)


@dataclass
class Finding:
    level: str
    year: int
    message: str
    # Подтверждению соседним признаком поддаётся только разрыв в числовом
    # ряду. Разнобой валют и дробления акций — про другое, и дефектом они не
    # становятся оттого, что в том же году нашлась опечатка.
    promotable: bool = False


@dataclass
class CompanyAudit:
    ticker: str
    company_type: str
    reports: int = 0
    verified: int = 0
    currencies: tuple = ()
    findings: list[Finding] = field(default_factory=list)

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    @property
    def clean(self) -> bool:
        return self.count(DEFECT) == 0


def _f(report, name: str) -> Optional[float]:
    value = getattr(report, name, None)
    return None if value is None else float(value)


def _num(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def _decade(a: float, b: float) -> Optional[int]:
    """Во сколько раз b больше a, если это почти ровно степень десяти."""
    if a <= 0 or b <= 0:
        return None
    ratio = max(a, b) / min(a, b)
    for power in DECADES:
        if abs(ratio - power) / power < DECADE_FIT:
            return power
    return None


def _check_balance(rep, out: list[Finding]) -> None:
    assets, liab, eq = (_f(rep, n) for n in ("total_assets", "total_liabilities", "equity"))
    if assets is None or liab is None or eq is None or not assets:
        return
    total = liab + eq
    share = abs(assets - total) / abs(assets)
    if share <= BALANCE_TOLERANCE:
        return

    if liab == assets:
        out.append(Finding(DEFECT, rep.fiscal_year,
                           f"обязательства {_num(liab)} в точности равны активам — "
                           f"поле скопировано"))
        return

    power = _decade(assets, total)
    if power:
        wrong, right = ("активы", total) if assets < total else ("обязательства+капитал", assets)
        out.append(Finding(DEFECT, rep.fiscal_year,
                           f"баланс расходится ровно в {power} раз — потерян разряд: "
                           f"{wrong} {_num(min(assets, total))} против {_num(max(assets, total))}"))
        return

    level = GAP if share <= NCI_TOLERANCE else DEFECT
    note = " (похоже на неконтролирующую долю — поля под неё в модели нет)" if level == GAP else ""
    out.append(Finding(level, rep.fiscal_year,
                       f"баланс не сходится на {share * 100:.1f}%: активы {_num(assets)}, "
                       f"обязательства+капитал {_num(total)}{note}"))


def _check_lender(rep, out: list[Finding]) -> None:
    gross = _f(rep, "gross_loans")
    if gross is None or gross <= 0:
        return
    allowance, npl = _f(rep, "loan_loss_allowance"), _f(rep, "npl_loans")
    if allowance is not None and allowance > gross:
        out.append(Finding(DEFECT, rep.fiscal_year,
                           f"резерв {_num(allowance)} больше портфеля {_num(gross)}"))
    if npl is not None and npl > gross:
        out.append(Finding(DEFECT, rep.fiscal_year,
                           f"обесцененные {_num(npl)} больше портфеля {_num(gross)}"))
    retail, corp = _f(rep, "loans_retail"), _f(rep, "loans_corporate")
    if retail is not None and corp is not None:
        share = abs(retail + corp - gross) / gross
        if share > 0.02:
            out.append(Finding(SUSPECT if share < 0.10 else DEFECT, rep.fiscal_year,
                               f"физлица+юрлица {_num(retail + corp)} против портфеля "
                               f"{_num(gross)} — расхождение {share * 100:.1f}%"))


def _check_ranges(rep, out: list[Finding]) -> None:
    for name in ("revenue", "total_assets", "gross_loans", "customer_deposits", "equity"):
        value = _f(rep, name)
        if value is not None and value < 0:
            level = SUSPECT if name == "equity" else DEFECT
            out.append(Finding(level, rep.fiscal_year, f"{name} отрицательный: {_num(value)}"))

    assets = _f(rep, "total_assets")
    if assets:
        for name, title in (("current_assets", "оборотные активы"), ("equity", "капитал")):
            value = _f(rep, name)
            if value is not None and value > assets * 1.01:
                out.append(Finding(DEFECT, rep.fiscal_year,
                                   f"{title} {_num(value)} больше активов {_num(assets)}"))


def _check_scale(reports: list, out: list[Finding]) -> None:
    """Скачок ровно в разряд — почти всегда опечатка, а не событие.

    Ряды разных валют не сравниваются: Норникель и НЛМК часть лет отчитывались
    в долларах, и переход USD → RUB даёт скачок в 60 раз на ровном месте.
    """
    by_currency = defaultdict(list)
    for rep in reports:
        by_currency[getattr(rep, "currency", None)].append(rep)

    for series_reports in by_currency.values():
        series_reports.sort(key=lambda r: r.fiscal_year)
        for name in SCALE_WATCH:
            series = [(r.fiscal_year, _f(r, name)) for r in series_reports]
            series = [(y, v) for y, v in series if v not in (None, 0)]
            if len(series) < 2:
                continue

            # Всплеск между двумя нормальными соседями — диагноз точный.
            spikes = set()
            for i in range(1, len(series) - 1):
                (y0, v0), (y1, v1), (y2, v2) = series[i - 1], series[i], series[i + 1]
                left, right = _decade(v0, v1), _decade(v1, v2)
                if left and left == right and (v1 > v0) == (v1 > v2):
                    spikes.add(y1)
                    out.append(Finding(
                        DEFECT, y1,
                        f"{name}: {y0} {_num(v0)} → {y1} {_num(v1)} → {y2} {_num(v2)} — "
                        f"выброс ровно в {left} раз",
                    ))

            # На краях ряда соседа с одной стороны нет, и подтвердить всплеск
            # нечем. Разница в десять раз за год — вещь возможная (прибыль
            # Софтлайна за 2025 действительно упала почти вдесятеро), поэтому
            # сама по себе она только повод посмотреть. А вот в сто и тысячу
            # раз ни одна из этих величин за год не меняется.
            for (y0, v0), (y1, v1) in ((series[0], series[1]), (series[-1], series[-2])):
                if y0 in spikes:
                    continue
                power = _decade(v0, v1)
                if power:
                    out.append(Finding(
                        SUSPECT if power == 10 else DEFECT, y0,
                        f"{name}: {y0} {_num(v0)} против {y1} {_num(v1)} — "
                        f"разница ровно в {power} раз на краю ряда",
                        promotable=True,
                    ))


def _check_equity_collapse(reports: list, out: list[Finding]) -> None:
    """Капитал упал, хотя год был прибыльным.

    Структурные проверки такое пропускают: баланс сходится, разрядов не
    теряли. А между тем упасть на треть прибыльная компания может, только
    раздав больше, чем заработала за годы, — или списав активы.
    """
    by_currency = defaultdict(list)
    for rep in reports:
        by_currency[getattr(rep, "currency", None)].append(rep)

    for series_reports in by_currency.values():
        series_reports.sort(key=lambda r: r.fiscal_year)
        series = [
            (r.fiscal_year, _f(r, "equity"), _f(r, "net_income"))
            for r in series_reports
        ]
        series = [(y, e, n) for y, e, n in series if e is not None and e > 0]
        for (y0, e0, _), (y1, e1, n1) in zip(series, series[1:]):
            # Только смежные годы: падение на треть за семь лет — обычная
            # история компании, за один год — уже вопрос.
            if y1 - y0 != 1:
                continue
            drop = (e0 - e1) / e0
            if drop <= EQUITY_COLLAPSE or n1 is None or n1 <= 0:
                continue
            out.append(Finding(
                SUSPECT, y1,
                f"капитал {y0} → {y1} упал на {drop * 100:.0f}% "
                f"({_num(e0)} → {_num(e1)}) при прибыли {_num(n1)}",
            ))


def _check_currency(reports: list, out: list[Finding]) -> None:
    currencies = {getattr(r, "currency", None) for r in reports}
    if len(currencies) > 1:
        names = ", ".join(sorted(str(c) for c in currencies))
        out.append(Finding(SUSPECT, max(r.fiscal_year for r in reports),
                           f"ряд в разных валютах ({names}) — динамика и мультипликаторы "
                           f"по годам несопоставимы"))


def _check_shares(reports: list, splits, out: list[Finding]) -> None:
    known = len(splits or [])
    series = sorted((r.fiscal_year, int(r.shares_issued)) for r in reports if r.shares_issued)
    jumps = 0
    for (y0, v0), (y1, v1) in zip(series, series[1:]):
        ratio = max(v0, v1) / min(v0, v1)
        if ratio >= 2:
            jumps += 1
            if jumps > known:
                out.append(Finding(SUSPECT, y1,
                                   f"число акций {y0} → {y1} в {ratio:.1f} раза "
                                   f"без записи о дроблении"))


def audit_company(company, reports) -> CompanyAudit:
    result = CompanyAudit(
        ticker=str(company.ticker),
        company_type=str(company.company_type),
        reports=len(reports),
        verified=sum(1 for r in reports if r.verified_by_analyst),
        currencies=tuple(sorted({str(getattr(r, "currency", "?")) for r in reports})),
    )
    for rep in reports:
        _check_balance(rep, result.findings)
        _check_lender(rep, result.findings)
        _check_ranges(rep, result.findings)
    _check_scale(reports, result.findings)
    _check_equity_collapse(reports, result.findings)
    _check_currency(reports, result.findings)
    _check_shares(reports, getattr(company, "share_splits", None), result.findings)
    _corroborate(result.findings)
    result.findings.sort(key=lambda f: (f.year, f.level))
    return result


def _corroborate(findings: list[Finding]) -> None:
    """Слабый сигнал становится дефектом, если год уже подтверждён сильным.

    Активы Башнефти за 2025 отличаются от прошлогодних ровно в десять раз —
    одного этого мало. Но за тот же год не сходится баланс, и сходится он
    ровно на недостающий разряд: два независимых признака указывают на одну
    опечатку.
    """
    proven = {f.year for f in findings if f.level == DEFECT}
    for f in findings:
        if f.level == SUSPECT and f.promotable and f.year in proven:
            f.level = DEFECT


def collect(wanted: set[str]) -> list[CompanyAudit]:
    db = SessionLocal()
    try:
        by_company = defaultdict(list)
        for rep in db.query(FinancialReport).filter(FinancialReport.period_type == "ANNUAL"):
            by_company[rep.company_id].append(rep)

        audits = []
        for company in db.query(Company).order_by(Company.ticker):
            if wanted and str(company.ticker).upper() not in wanted:
                continue
            reports = by_company.get(int(company.id), [])
            if reports:
                audits.append(audit_company(company, reports))
        return audits
    finally:
        db.close()



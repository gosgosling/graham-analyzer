"""Аудит достоверности данных — командная строка.

Проверки живут в `app.services.analysis.data_audit`: ими пользуется и эта
команда, и страница базового множителя, которой нужен список компаний,
пригодных к показу.

    python -m scripts.audit_data              # сводка и список дефектов
    python -m scripts.audit_data --clean      # только пригодные компании
    python -m scripts.audit_data --all        # включая suspect
    python -m scripts.audit_data SBER LKOH    # выборочно, с подробностями
"""

from __future__ import annotations

import sys

from app.services.analysis.data_audit import (
    DEFECT,
    GAP,
    SUSPECT,
    CompanyAudit,
    collect,
)


def _print_detail(audits: list[CompanyAudit], levels: tuple) -> None:
    for a in audits:
        shown = [f for f in a.findings if f.level in levels]
        if not shown:
            continue
        print(f"\n{a.ticker}  ({a.company_type}, {a.reports} лет, "
              f"{'/'.join(a.currencies)})")
        for f in shown:
            tag = {DEFECT: "ДЕФЕКТ ", GAP: "пробел ", SUSPECT: "смотреть"}[f.level]
            print(f"   {tag} {f.year}  {f.message}")


def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    wanted = {a.upper() for a in sys.argv[1:] if not a.startswith("--")}
    audits = collect(wanted)

    clean = [a for a in audits if a.clean]
    broken = sorted((a for a in audits if not a.clean),
                    key=lambda a: -a.count(DEFECT))

    if "--clean" in flags:
        print(f"Без дефектов: {len(clean)} из {len(audits)}\n")
        for a in sorted(clean, key=lambda x: (-x.reports, x.ticker)):
            note = []
            if a.count(GAP):
                note.append(f"{a.count(GAP)} пробел(ов) схемы")
            if a.count(SUSPECT):
                note.append(f"{a.count(SUSPECT)} к просмотру")
            print(f"  {a.ticker:<8}{a.company_type:<11}{a.reports:>3} лет, "
                  f"проверено {a.verified:>2}   {'; '.join(note)}")
        return 0

    if wanted:
        _print_detail(audits, (DEFECT, GAP, SUSPECT))
        return 0

    print("=" * 72)
    print(f"КОМПАНИЙ С ГОДОВЫМИ ОТЧЁТАМИ: {len(audits)}")
    print(f"  без дефектов:      {len(clean):>4}")
    print(f"  с дефектами:       {len(broken):>4}")
    print("-" * 72)
    for level, title in ((DEFECT, "заведомых ошибок ввода"),
                         (GAP, "расхождений из-за отсутствующего поля"),
                         (SUSPECT, "поводов посмотреть глазами")):
        print(f"  {title:<40}{sum(a.count(level) for a in audits):>5}")
    print("=" * 72)

    print("\nЗАВЕДОМЫЕ ОШИБКИ ВВОДА")
    _print_detail(broken, (DEFECT,))

    if "--all" in flags:
        print("\n\nПОВОДЫ ПОСМОТРЕТЬ ГЛАЗАМИ")
        _print_detail(audits, (SUSPECT,))

    print(f"\n\nПригодные к показу: python -m scripts.audit_data --clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

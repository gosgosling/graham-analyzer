# -*- coding: utf-8 -*-
"""
Fix non-RUB reports: currency normalization + MOEX price in report currency.

Previously the AI parser stored MOEX price (always in RUB) in price_per_share
regardless of report currency. For non-RUB reports this broke P/E and P/B
calculations: calc_multipliers multiplies price_per_share by exchange_rate
assuming the price is in report currency. The result was
price_moex * rate * shares instead of price_moex * shares.

Migration steps:
  1. Normalize currency field using schemas._normalize_currency
     (e.g. "rub." / "rub" / "R" -> "RUB").
  2. For currency != RUB with non-null exchange_rate and a price that looks
     like RUB (> 500), divide by exchange_rate.
  3. Recompute report_based multipliers for touched reports.

Run: python migrate_fix_fx_prices.py
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models.financial_report import FinancialReport
from app.services.analysis.multiplier_service import save_report_based_multiplier
from app.services.report_parser.schemas import _normalize_currency

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate")


def _looks_like_rub(v):
    return v is not None and v > 500


def run() -> None:
    db = SessionLocal()
    try:
        reports = db.query(FinancialReport).all()
        normalized_currency = 0
        converted_price = 0
        recalc_ids: list[int] = []

        for r in reports:
            touched = False
            raw_cur = r.currency or "RUB"
            norm_cur = _normalize_currency(raw_cur)
            if norm_cur != raw_cur:
                log.info("[id=%s] currency: %r -> %s", r.id, raw_cur, norm_cur)
                r.currency = norm_cur  # type: ignore[assignment]
                normalized_currency += 1
                touched = True

            cur_upper = (r.currency or "RUB").upper()

            if cur_upper != "RUB" and r.exchange_rate and float(r.exchange_rate) > 0:
                rate = float(r.exchange_rate)
                pps = float(r.price_per_share) if r.price_per_share is not None else None
                paf = float(r.price_at_filing) if r.price_at_filing is not None else None

                if _looks_like_rub(pps):
                    new_pps = round(pps / rate, 4)
                    log.info(
                        "[id=%s company=%s fy=%s] price_per_share: %.2f RUB / %.4f = %.4f %s",
                        r.id, r.company_id, r.fiscal_year, pps, rate, new_pps, cur_upper,
                    )
                    r.price_per_share = new_pps  # type: ignore[assignment]
                    converted_price += 1
                    touched = True

                if _looks_like_rub(paf):
                    new_paf = round(paf / rate, 4)
                    log.info(
                        "[id=%s company=%s fy=%s] price_at_filing: %.2f RUB / %.4f = %.4f %s",
                        r.id, r.company_id, r.fiscal_year, paf, rate, new_paf, cur_upper,
                    )
                    r.price_at_filing = new_paf  # type: ignore[assignment]
                    converted_price += 1
                    touched = True

            if touched:
                recalc_ids.append(r.id)

        if not recalc_ids:
            log.info("Nothing to migrate; data is already clean.")
            return

        db.flush()

        # save_report_based_multiplier internally handles stale cleanup and
        # commits after each report. No need to call delete_multipliers_for_report
        # ourselves (autoflush would otherwise see the pending-delete row and
        # cause a session error).
        for rid in recalc_ids:
            r = db.query(FinancialReport).filter(FinancialReport.id == rid).first()
            if r is None:
                continue
            m = save_report_based_multiplier(db, r)
            if m:
                log.info(
                    "[id=%s] report_based: P/E=%s P/B=%s market_cap(mln_rub)=%s price_used=%s",
                    rid, m.pe_ratio, m.pb_ratio, m.market_cap, m.price_used,
                )

        log.info(
            "Done: currencies normalized %d, prices converted %d, reports recomputed %d.",
            normalized_currency, converted_price, len(recalc_ids),
        )

    except Exception:
        db.rollback()
        log.exception("Migration failed, rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()

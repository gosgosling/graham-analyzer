/** Разрешение количества акций (зеркало backend share_counts.py). */

export interface ShareCountFields {
  shares_issued?: number | null;
  shares_outstanding?: number | null;
  shares_weighted_avg?: number | null;
  treasury_shares?: number | null;
}

/** Акции в обращении: явное значение или размещённые − казначейские. */
export function computeCirculationShares(fields: ShareCountFields): number | null {
  const { shares_outstanding, shares_issued, treasury_shares } = fields;

  if (shares_outstanding != null) {
    return shares_outstanding;
  }

  if (shares_issued == null) {
    return null;
  }

  if (treasury_shares != null) {
    return Math.max(shares_issued - treasury_shares, 0);
  }

  return null;
}

/** Количество акций для капитализации / P/E / P/B. */
export function resolveSharesForMultipliers(fields: ShareCountFields): number | null {
  const circulation = computeCirculationShares(fields);
  if (circulation != null) return circulation;

  if (fields.shares_weighted_avg != null) return fields.shares_weighted_avg;
  if (fields.shares_issued != null) return fields.shares_issued;

  return null;
}

export const SHARE_INT_FIELDS = new Set([
  'shares_issued',
  'shares_outstanding',
  'shares_weighted_avg',
  'treasury_shares',
]);

export function isShareIntField(field: string): boolean {
  return SHARE_INT_FIELDS.has(field);
}

/** Пояснение базы капитализации (из API или клиентский расчёт). */
export function explainSharesCapBasis(
  fields: ShareCountFields,
  sharesUsed: number | null | undefined,
): string | null {
  if (sharesUsed == null) return null;

  const su = sharesUsed;
  const fmt = su.toLocaleString('ru-RU');
  const circulation = computeCirculationShares(fields);
  const hasOutstanding = fields.shares_outstanding != null;
  const hasWeighted = fields.shares_weighted_avg != null;
  const hasIssued = fields.shares_issued != null;
  const legacyDup =
    hasOutstanding &&
    hasIssued &&
    fields.shares_outstanding === fields.shares_issued &&
    fields.shares_weighted_avg == null &&
    fields.treasury_shares == null;

  if (legacyDup && hasIssued && su === fields.shares_issued) {
    return (
      `Использовано размещённое (общее) количество — ${fmt} шт., ` +
      'т.к. не указаны: акции в обращении, средневзвешенное количество.'
    );
  }

  if (circulation != null && su === circulation) {
    if (hasOutstanding) {
      return (
        `Использованы акции в обращении — ${fmt} шт.: ` +
        'это предпочтительная база для расчёта капитализации.'
      );
    }
    const issuedFmt = fields.shares_issued!.toLocaleString('ru-RU');
    const treasuryFmt = fields.treasury_shares!.toLocaleString('ru-RU');
    return (
      `Использованы акции в обращении — ${fmt} шт. ` +
      `(размещённые ${issuedFmt} минус казначейские ${treasuryFmt}).`
    );
  }

  if (hasWeighted && su === fields.shares_weighted_avg) {
    return (
      `Использовано средневзвешенное количество — ${fmt} шт., ` +
      'т.к. в отчёте не указаны акции в обращении.'
    );
  }

  if (hasIssued && su === fields.shares_issued) {
    const missing: string[] = [];
    if (circulation == null) missing.push('акции в обращении');
    if (!hasWeighted) missing.push('средневзвешенное количество');
    if (missing.length > 0) {
      return (
        `Использовано размещённое (общее) количество — ${fmt} шт., ` +
        `т.к. не указаны: ${missing.join(', ')}.`
      );
    }
    return `Использовано размещённое (общее) количество — ${fmt} шт.`;
  }

  return `Использовано ${fmt} шт. для расчёта капитализации.`;
}

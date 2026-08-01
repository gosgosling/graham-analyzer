/**
 * Разбор мультипликаторов отчёта: не только «сколько», но и «из чего».
 *
 * Модалка просмотра должна отвечать на вопрос «почему P/E такой», а для этого
 * нужны обе части дроби с их значениями. Формулы повторяют бэкенд
 * (`calc_multipliers.py`) — это осознанное зеркало, как у FCF и чистого долга,
 * и держится оно тестами на общих примерах.
 *
 * Все денежные величины берутся в рублёвом представлении (`*_rub`), которое
 * считает бэкенд: у валютных отчётов иначе разъедутся числитель и знаменатель.
 */
import type { FinancialReport } from '../types';
import { resolveSharesForMultipliers } from './shareCounts';

export interface MetricExplanation {
  key: string;
  label: string;
  /** Значение мультипликатора; null — не хватает данных. */
  value: number | null;
  /** Единица измерения для отображения. */
  unit: '' | '%';
  /** Словесная формула: «Капитализация ÷ Чистая прибыль». */
  formula: string;
  /** Подстановка с числами; пусто, если считать не из чего. */
  substitution: string;
  /** Чего именно не хватает — вместо молчаливого прочерка. */
  missing?: string;
}

const MLN = 1_000_000;

function num(v: number | null | undefined): number | null {
  return v === null || v === undefined || Number.isNaN(v) ? null : v;
}

/** Денежная величина в млн ₽ → «21,6 млрд ₽» / «842 млн ₽». */
export function fmtMlnRub(value: number | null): string {
  if (value === null) return '—';
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} трлн ₽`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(2)} млрд ₽`;
  return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн ₽`;
}

/** Капитализация на дату отчёта, млн ₽: цена × акции. */
export function marketCapMln(report: FinancialReport): number | null {
  const price = num(report.price_per_share_rub) ?? num(report.price_per_share);
  const shares = resolveSharesForMultipliers(report);
  if (price === null || shares === null) return null;
  return (price * shares) / MLN;
}

function ratio(
  key: string,
  label: string,
  formula: string,
  numerator: { value: number | null; text: string; name: string },
  denominator: { value: number | null; text: string; name: string },
  options: { unit?: '' | '%'; percent?: boolean; positiveDenominator?: boolean } = {},
): MetricExplanation {
  const { unit = '', percent = false, positiveDenominator = false } = options;

  if (numerator.value === null || denominator.value === null) {
    const lacking = [
      numerator.value === null ? numerator.name : null,
      denominator.value === null ? denominator.name : null,
    ].filter(Boolean);
    return {
      key, label, unit, formula, value: null, substitution: '',
      missing: `Не заполнено: ${lacking.join(', ')}`,
    };
  }
  if (denominator.value === 0 || (positiveDenominator && denominator.value < 0)) {
    return {
      key, label, unit, formula, value: null,
      substitution: `${numerator.text} ÷ ${denominator.text}`,
      missing:
        denominator.value === 0
          ? `${denominator.name} = 0 — деление невозможно`
          : `${denominator.name} отрицателен — показатель не имеет смысла`,
    };
  }

  const raw = numerator.value / denominator.value;
  return {
    key,
    label,
    unit,
    formula,
    value: Math.round((percent ? raw * 100 : raw) * 100) / 100,
    substitution: `${numerator.text} ÷ ${denominator.text}`,
  };
}

/**
 * Мультипликаторы отчёта с расшифровкой.
 *
 * Для банка D/E и Current Ratio не возвращаются: депозиты клиентов —
 * обязательства по природе, а ликвидность банка меряется нормативами ЦБ.
 * Вместо них — Cost-to-Income.
 */
export function explainReportMultipliers(report: FinancialReport): MetricExplanation[] {
  const isBank = report.report_type === 'bank';
  const cap = marketCapMln(report);
  const capText = fmtMlnRub(cap);
  const profit = num(report.net_income_rub) ?? num(report.net_income);
  const equity = num(report.equity_rub) ?? num(report.equity);
  const price = num(report.price_per_share_rub) ?? num(report.price_per_share);
  const dps = num(report.dividends_per_share);

  const out: MetricExplanation[] = [
    ratio(
      'pe', 'P/E', 'Капитализация ÷ Чистая прибыль',
      { value: cap, text: capText, name: 'цена или количество акций' },
      { value: profit, text: fmtMlnRub(profit), name: 'чистая прибыль' },
      { positiveDenominator: true },
    ),
    ratio(
      'pb', 'P/B', 'Капитализация ÷ Собственный капитал',
      { value: cap, text: capText, name: 'цена или количество акций' },
      { value: equity, text: fmtMlnRub(equity), name: 'капитал' },
      { positiveDenominator: true },
    ),
    ratio(
      'roe', 'ROE', 'Чистая прибыль ÷ Собственный капитал',
      { value: profit, text: fmtMlnRub(profit), name: 'чистая прибыль' },
      { value: equity, text: fmtMlnRub(equity), name: 'капитал' },
      { unit: '%', percent: true, positiveDenominator: true },
    ),
  ];

  if (isBank) {
    out.push(
      ratio(
        'cir', 'Cost/Income', 'Операционные расходы ÷ Операционные доходы',
        {
          value: num(report.operating_expenses),
          text: fmtMlnRub(num(report.operating_expenses)),
          name: 'операционные расходы',
        },
        {
          value: num(report.revenue_rub) ?? num(report.revenue),
          text: fmtMlnRub(num(report.revenue_rub) ?? num(report.revenue)),
          name: 'операционные доходы',
        },
        { unit: '%', percent: true },
      ),
    );
  } else {
    out.push(
      ratio(
        'de', 'Долг/Капитал', 'Итого обязательства ÷ Собственный капитал',
        {
          value: num(report.total_liabilities_rub) ?? num(report.total_liabilities),
          text: fmtMlnRub(num(report.total_liabilities_rub) ?? num(report.total_liabilities)),
          name: 'обязательства',
        },
        { value: equity, text: fmtMlnRub(equity), name: 'капитал' },
      ),
      ratio(
        'cr', 'Current Ratio', 'Оборотные активы ÷ Краткосрочные обязательства',
        {
          value: num(report.current_assets_rub) ?? num(report.current_assets),
          text: fmtMlnRub(num(report.current_assets_rub) ?? num(report.current_assets)),
          name: 'оборотные активы',
        },
        {
          value: num(report.current_liabilities_rub) ?? num(report.current_liabilities),
          text: fmtMlnRub(num(report.current_liabilities_rub) ?? num(report.current_liabilities)),
          name: 'краткосрочные обязательства',
        },
      ),
    );
  }

  out.push(
    ratio(
      'dy', 'Div. Yield', 'Дивиденд на акцию ÷ Цена акции',
      {
        value: report.dividends_paid ? dps : null,
        text: dps !== null ? `${dps.toLocaleString('ru-RU', { maximumFractionDigits: 6 })} ₽` : '—',
        name: report.dividends_paid ? 'дивиденд на акцию' : 'дивиденды за период (не выплачивались)',
      },
      {
        value: price,
        text: price !== null ? `${price.toLocaleString('ru-RU', { maximumFractionDigits: 6 })} ₽` : '—',
        name: 'цена акции',
      },
      { unit: '%', percent: true },
    ),
  );

  return out;
}
